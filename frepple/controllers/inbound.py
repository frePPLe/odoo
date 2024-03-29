# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 by frePPLe bv
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
#

import odoo
import logging
from xml.etree.cElementTree import iterparse
from datetime import datetime

logger = logging.getLogger(__name__)


class importer(object):
    def __init__(self, req, database=None, company=None, mode=1):
        self.env = req.env
        self.database = database
        self.company = company
        self.datafile = req.httprequest.files.get("frePPLe plan")

        # The mode argument defines different types of runs:
        #  - Mode 1:
        #    Export of the complete plan. This first erase all previous frePPLe
        #    proposals in draft state.
        #  - Mode 2:
        #    Incremental export of some proposed transactions from frePPLe.
        #    In this mode mode we are not erasing any previous proposals.
        #  - Mode 3:
        #    odoo_export command will use that mode starting from the second page.
        #    In this mode, we make sure that no aggregation of exported quantities
        #    is made.
        #    In this mode mode we are not erasing any previous proposals.
        self.mode = int(mode)

        # User to be set as responsible on new objects in incremental exports
        self.actual_user = req.httprequest.form.get("actual_user", None)
        if self.mode == 2 and self.actual_user:
            try:
                self.actual_user = self.env["res.users"].search(
                    [("login", "=", self.actual_user)]
                )[0]
            except Exception:
                self.actual_user = None
        else:
            self.actual_user = None

    def run(self):
        msg = []
        if self.actual_user:
            proc_order = self.env["purchase.order"].with_user(self.actual_user)
            proc_orderline = self.env["purchase.order.line"].with_user(self.actual_user)
            mfg_order = self.env["mrp.production"].with_user(self.actual_user)
            mfg_workorder = self.env["mrp.workorder"].with_user(self.actual_user)
            stck_picking_type = self.env["stock.picking.type"].with_user(
                self.actual_user
            )
        else:
            proc_order = self.env["purchase.order"]
            proc_orderline = self.env["purchase.order.line"]
            mfg_order = self.env["mrp.production"]
            mfg_workorder = self.env["mrp.workorder"]
            stck_picking_type = self.env["stock.picking.type"]
        if self.mode == 1:
            # Cancel previous draft purchase quotations
            m = self.env["purchase.order"]
            recs = m.search([("state", "=", "draft"), ("origin", "=", "frePPLe")])
            recs.write({"state": "cancel"})
            recs.unlink()
            msg.append("Removed %s old draft purchase orders" % len(recs))

            # Cancel previous draft manufacturing orders
            recs = mfg_order.search(
                [
                    "|",
                    ("state", "=", "draft"),
                    ("state", "=", "cancel"),
                    ("origin", "=", "frePPLe"),
                ]
            )
            recs.write({"state": "cancel"})
            recs.unlink()
            msg.append("Removed %s old draft manufacturing orders" % len(recs))

        # Parsing the XML data file
        countproc = 0
        countmfg = 0

        # dictionary that stores as key the supplier id and the associated po id
        # this dict is used to aggregate the exported POs for a same supplier
        # into one PO in odoo with multiple lines
        supplier_reference = {}

        # dictionary that stores as key a tuple (product id, supplier id)
        # and as value a poline odoo object
        # this dict is used to aggregate POs for the same product supplier
        # into one PO with sum of quantities and min date
        product_supplier_dict = {}

        # Mapping between frepple-generated MO reference and their odoo id.
        mo_references = {}

        for event, elem in iterparse(self.datafile, events=("start", "end")):
            if event == "end" and elem.tag == "operationplan":
                uom_id, item_id = elem.get("item_id").split(",")
                try:
                    ordertype = elem.get("ordertype")
                    if ordertype == "PO":
                        # Create purchase order
                        supplier_id = int(elem.get("supplier").split(" ", 1)[0])
                        quantity = elem.get("quantity")
                        date_planned = elem.get("end")
                        if date_planned:
                            date_planned = datetime.strptime(
                                date_planned, "%Y-%m-%d %H:%M:%S"
                            )
                        date_ordered = elem.get("start")
                        if date_ordered:
                            date_ordered = datetime.strptime(
                                date_ordered, "%Y-%m-%d %H:%M:%S"
                            )
                        if supplier_id not in supplier_reference:
                            po = proc_order.create(
                                {
                                    "company_id": self.company.id,
                                    "partner_id": int(
                                        elem.get("supplier").split(" ", 1)[0]
                                    ),
                                    # TODO Odoo has no place to store the location and criticality
                                    # int(elem.get('location_id')),
                                    # elem.get('criticality'),
                                    "origin": "frePPLe",
                                }
                            )
                            supplier_reference[supplier_id] = {
                                "id": po.id,
                                "min_planned": date_planned,
                                "min_ordered": date_ordered,
                                "po": po,
                            }
                        else:
                            if (
                                date_planned
                                < supplier_reference[supplier_id]["min_planned"]
                            ):
                                supplier_reference[supplier_id][
                                    "min_planned"
                                ] = date_planned
                            if (
                                date_ordered
                                < supplier_reference[supplier_id]["min_ordered"]
                            ):
                                supplier_reference[supplier_id][
                                    "min_ordered"
                                ] = date_ordered

                        if (item_id, supplier_id) not in product_supplier_dict:
                            product = self.env["product.product"].browse(int(item_id))
                            product_supplierinfo = self.env[
                                "product.supplierinfo"
                            ].search(
                                [
                                    ("name", "=", supplier_id),
                                    (
                                        "product_tmpl_id",
                                        "=",
                                        product.product_tmpl_id.id,
                                    ),
                                    ("min_qty", "<=", quantity),
                                ],
                                limit=1,
                                order="min_qty desc",
                            )
                            if product_supplierinfo:
                                price_unit = product_supplierinfo.price
                            else:
                                price_unit = 0
                            po_line = proc_orderline.create(
                                {
                                    "order_id": supplier_reference[supplier_id]["id"],
                                    "product_id": int(item_id),
                                    "product_qty": quantity,
                                    "product_uom": int(uom_id),
                                    "date_planned": date_planned,
                                    "price_unit": price_unit,
                                    "name": elem.get("item"),
                                }
                            )
                            # Aggregation of quantities under the same PO line
                            # only happens in incremental export
                            if self.mode == 2:
                                product_supplier_dict[(item_id, supplier_id)] = po_line
                        else:
                            po_line = product_supplier_dict[(item_id, supplier_id)]
                            po_line.date_planned = min(
                                po_line.date_planned,
                                date_planned,
                            )
                            po_line.product_qty = po_line.product_qty + float(quantity)
                        countproc += 1
                    # TODO Create a distribution order
                    # elif ordertype == "DO":
                    #      create stock transfer
                    elif ordertype == "WO":
                        # Update a workorder
                        if elem.get("owner") in mo_references:
                            # Newly created MO
                            mo = mo_references[elem.get("owner")]
                        else:
                            # Existing MO
                            mo = mfg_order.search([("name", "=", elem.get("owner"))])
                        if mo:
                            wo = mfg_workorder.search(
                                [
                                    (
                                        "production_id",
                                        "=",
                                        mo.id,
                                    ),
                                    (
                                        "operation_id",
                                        "=",
                                        int(elem.get("operation").rsplit(" ", 1)[1]),
                                    ),
                                ]
                            )
                            if wo and wo.state == "pending":
                                wo.write(
                                    {
                                        "date_planned_start": elem.get("start"),
                                        "date_planned_finished": elem.get("end"),
                                    }
                                )
                    else:
                        # Create manufacturing order
                        warehouse = int(elem.get("location_id"))
                        picking = stck_picking_type.search(
                            [
                                ("code", "=", "mrp_operation"),
                                ("company_id", "=", self.company.id),
                                ("warehouse_id", "=", warehouse),
                            ],
                            limit=1,
                        )

                        # update the context with the default picking type
                        # to set correct src/dest locations
                        if picking:
                            self.env.context = dict(self.env.context)
                            self.env.context.update(
                                {
                                    "default_picking_type_id": picking.id,
                                }
                            )

                        mo = mfg_order.create(
                            {
                                "product_qty": elem.get("quantity"),
                                "date_planned_start": elem.get("start"),
                                "date_planned_finished": elem.get("end"),
                                "product_id": int(item_id),
                                "company_id": self.company.id,
                                "product_uom_id": int(uom_id),
                                "picking_type_id": picking.id,
                                "bom_id": int(elem.get("operation").rsplit(" ", 1)[1]),
                                "qty_producing": 0.00,
                                # TODO no place to store the criticality
                                # elem.get('criticality'),
                                "origin": "frePPLe",
                            }
                        )
                        # Remember odoo name for the MO reference passed by frepple.
                        # This mapping is later used when importing WO.
                        mo_references[elem.get("reference")] = mo
                        mo._onchange_workorder_ids()
                        mo._onchange_move_raw()
                        mo._create_update_move_finished()
                        # mo.action_confirm()  # confirm MO
                        # mo._plan_workorders() # plan MO
                        # mo.action_assign() # reserve material
                        countmfg += 1
                except Exception as e:
                    logger.error("Exception %s" % e)
                    msg.append(str(e))
                # Remove the element now to keep the DOM tree small
                root.clear()
            elif event == "start" and elem.tag == "operationplans":
                # Remember the root element
                root = elem

        # Update PO RFQ order_deadline and receipt date
        for sup in supplier_reference.values():
            if sup["min_planned"]:
                sup["po"].date_planned = sup["min_planned"]
            if sup["min_ordered"]:
                sup["po"].date_order = sup["min_ordered"]

        # Be polite, and reply to the post
        msg.append("Processed %s uploaded procurement orders" % countproc)
        msg.append("Processed %s uploaded manufacturing orders" % countmfg)
        return "\n".join(msg)
