# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 by frePPLe bv
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from datetime import datetime

from odoo import fields, models, api
from odoo.exceptions import UserError

import logging
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)


class FreppleRecommendation(models.Model):
    _name = "frepple.recommendation"
    _description = "Frepple Recommendations"

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )

    tab = fields.Selection(
        [
            ("purchase", "Purchase"),
            ("mrp", "Manufacturing"),
            ("sale", "Sales"),
            ("stock", "Inventory"),
        ],
        string="Tab",
        required=True,
    )

    type = fields.Selection(
        [
            ("purchase", "purchase"),
            ("produce", "produce"),
            ("reschedule", "reschedule"),
            ("adjustreorderingrule", "adjustreorderingrule"),
            ("latedelivery", "late delivery"),
        ],
        string="Type",
        required=True,
    )

    startdate = fields.Datetime(string="Start Date")
    enddate = fields.Datetime(string="End Date")

    product_id = fields.Many2one(
        "product.product",
        string="Product",
        ondelete="cascade",
    )

    quantity = fields.Float(string="Quantity")

    # for specific recommendation data (partner_id, operation...)
    data = fields.Json(string="Data (JSON)", default=dict)

    recommendation = fields.Html(string="Recommendation")

    related_data_id = fields.Reference(
        selection="_get_related_data_selection",
        string="Related Data",
        ondelete="cascade",
    )

    @api.model
    def _get_related_data_selection(self):
        return [
            ("res.partner", "Vendor"),
            ("sale.order.line", "Sales Order Line"),
            ("mrp.production", "Manufacturing Order"),
        ]

    # Make sure the user cannot create a recommendation.
    # backend should create recommendations like this:
    # self.env["frepple.recommendation"].with_context(frepple_import=True).create(vals)
    @api.model_create_multi
    def create(self, vals_list):
        # Check context once for the whole batch
        if not self.env.context.get("frepple_import"):
            raise UserError("FrePPLe recommendations cannot be created manually.")

        # Process each dictionary in the list
        for vals in vals_list:
            if vals.get("recommendation"):
                vals["recommendation"] = self._format_recommendation(
                    vals.get("recommendation")
                )

        # Pass the entire list to the super call
        return super().create(vals_list)

    def action_approve(self):
        to_unlink = self.browse()  # empty recordset

        # One PO per supplier
        # key is supplier id, value is po object
        pos = {}

        # One PO line per supplier,product
        # key is (supplier_id, product_id)
        # value is po line
        po_lines = {}

        for rec in self:
            if rec.type == "purchase" and rec.related_data_id:
                # Extract vendor from the polymorphic Reference field
                if rec.related_data_id._name != "res.partner":
                    continue
                vendor = rec.related_data_id

                # 1. Check if a PO already exists for that supplier
                if vendor.id in pos:
                    po = pos[vendor.id]

                # 2 Else create a PO
                else:
                    po_args = {
                        "company_id": self.env.company.id,
                        "partner_id": vendor.id,
                    }
                    po = (
                        self.env["purchase.order"]
                        .with_user(self.env.user)
                        .create(po_args)
                    )
                    po.origin = "frePPLe"

                    pos[vendor.id] = po

                # 2. check if a Purchase Order Line already exists for that product
                product = rec.product_id

                if (vendor.id, product.id) in po_lines:
                    po_line = po_lines[(vendor.id, product.id)]
                    po_line.date_planned = min(po_line.date_planned, rec.enddate)
                    po_line.product_qty += rec.quantity
                else:
                    po_line = (
                        self.env["purchase.order.line"]
                        .with_user(self.env.user)
                        .create(
                            {
                                "order_id": po.id,
                                "product_id": product.id,
                                "product_qty": rec.quantity,
                                "uom_id": product.uom_id.id,
                            }
                        )
                    )

                    vals = po_line._prepare_purchase_order_line(
                        product,
                        rec.quantity,
                        product.uom_id,
                        self.company_id,
                        po.partner_id,
                        po,
                    )

                    vals["date_planned"] = rec.enddate
                    po_line.write(vals)
                    po_lines[(vendor.id, product.id)] = po_line

                # Mark recommendation for deletion
                to_unlink |= rec

            elif rec.type == "produce":
                # 1. Create Manufacturing Order
                mo_args = {
                    "company_id": self.env.company.id,
                    "bom_id": rec.data["bom_id"],
                    "product_qty": rec.quantity,
                    "date_start": rec.startdate,
                    "date_finished": rec.enddate,
                    "product_id": rec.product_id.id,
                    "uom_id": rec.product_id.uom_id.id,
                    # "picking_type_id": picking.id,
                    "qty_producing": 0.00,
                    "origin": "frePPLe",
                }
                mo = self.env["mrp.production"].with_user(self.env.user).create(mo_args)

                if (
                    hasattr(mo, "workorder_ids")
                    and mo.workorder_ids
                    and rec.data.get("workorders")
                ):
                    index = 0
                    for wo in mo.workorder_ids:
                        try:
                            wo.date_start = datetime.fromisoformat(
                                rec.data.get("workorders")[index][1]
                            )
                            wo.date_finished = datetime.fromisoformat(
                                rec.data.get("workorders")[index][2]
                            )
                        except:
                            wo.date_finished = datetime.fromisoformat(
                                rec.data.get("workorders")[index][2]
                            )
                            wo.date_start = datetime.fromisoformat(
                                rec.data.get("workorders")[index][1]
                            )

                        index += 1

                # Mark recommendation for deletion
                to_unlink |= rec
            elif rec.type == "reschedule" and rec.related_data_id:
                # For reschedule, related_data_id should be mrp.production
                if rec.related_data_id._name != "mrp.production":
                    continue
                mo = rec.related_data_id

                if (
                    hasattr(mo, "workorder_ids")
                    and mo.workorder_ids
                    and rec.data.get("workorders")
                ):
                    index = 0
                    for wo in mo.workorder_ids:
                        try:
                            wo.date_start = datetime.fromisoformat(
                                rec.data.get("workorders")[index][1]
                            )
                            wo.date_finished = datetime.fromisoformat(
                                rec.data.get("workorders")[index][2]
                            )
                        except:
                            wo.date_finished = datetime.fromisoformat(
                                rec.data.get("workorders")[index][2]
                            )
                            wo.date_start = datetime.fromisoformat(
                                rec.data.get("workorders")[index][1]
                            )
                        index += 1
                else:
                    mo.date_start = rec.startdate
                to_unlink |= rec

        # unlink ALL approved recommendations at once
        if to_unlink:
            to_unlink.unlink()

        return True

    # Used to format the recommendation in the list view
    def _format_recommendation(self, raw_text):
        lines = raw_text.split("\\n")
        if not lines:
            return ""
        first_line = f"<b>{lines[0]}</b>"
        if len(lines) > 1:
            # Wrap remaining lines in a small tag
            other_lines = "<br/>".join(lines[1:])
            return f"{first_line}<br/><small class='text-muted'>{other_lines}</small>"
        return first_line

    def action_open_related_data(self):
        """Open the related record in a new form window."""
        self.ensure_one()
        if not self.related_data_id:
            return False

        return {
            "type": "ir.actions.act_window",
            "res_model": self.related_data_id._name,
            "res_id": self.related_data_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_forecast(self):
        self.ensure_one()
        if not self.product_id:
            return False

        # This method is defined in the 'stock' module and returns the correct action.
        action = self.product_id.action_product_forecast_report()

        # Ensure the context is pointing to our specific product
        action["context"] = {
            "active_id": self.product_id.id,
            "active_model": "product.product",
        }
        return action
