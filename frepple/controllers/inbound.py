# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 by frePPLe bv
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero
# General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
import odoo
import logging
from xml.etree.cElementTree import iterparse
from datetime import datetime
from pytz import timezone, UTC

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
        self.mode = int(mode)

        # Pick up the timezone of the connector user (or UTC if not set)
        try:
            usr = self.env["res.users"].browse(ids=[req.uid]).read(["tz"])[0]
            self.timezone = timezone(usr["tz"] or "UTC")
        except Exception as e:
            self.timezone = timezone("UTC")

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
            mfg_workcenter = self.env["mrp.workcenter"].with_user(self.actual_user)
            stck_picking_type = self.env["stock.picking.type"].with_user(
                self.actual_user
            )
            stck_picking = self.env["stock.picking"].with_user(self.actual_user)
            stck_move = self.env["stock.move"].with_user(self.actual_user)
        else:
            proc_order = self.env["purchase.order"]
            proc_orderline = self.env["purchase.order.line"]
            mfg_order = self.env["mrp.production"]
            mfg_workorder = self.env["mrp.workorder"]
            mfg_workcenter = self.env["mrp.workcenter"]
            stck_picking_type = self.env["stock.picking.type"]
            stck_picking = self.env["stock.picking"]
            stck_move = self.env["stock.move"]
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
        wo_data = []

        for event, elem in iterparse(self.datafile, events=("start", "end")):
            if event == "start" and elem.tag == "workorder" and elem.get("operation"):
                try:
                    wo = {
                        "operation": elem.get("operation"),
                        "id": int(elem.get("operation").rsplit("- ", 1)[-1]),
                    }
                    st = elem.get("start")
                    if st:
                        try:
                            wo["start"] = datetime.strptime(st, "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass
                    nd = elem.get("end")
                    if st:
                        try:
                            wo["end"] = datetime.strptime(nd, "%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass
                    wo_data.append(wo)
                except Exception:
                    pass
            elif event == "start" and elem.tag == "resource" and wo_data:
                try:
                    res = {
                        "name": elem.get("name"),
                        "id": int(elem.get("id")),
                        "quantity": float(elem.get("quantity") or 0),
                    }
                    if "workcenters" in wo_data[-1]:
                        wo_data[-1]["workcenters"].append(res)
                    else:
                        wo_data[-1]["workcenters"] = [res]
                except Exception:
                    pass
            elif event == "end" and elem.tag == "operationplan":
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
                            po.payment_term_id = (
                                po.partner_id.property_supplier_payment_term_id.id
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

                            if product_supplierinfo:
                                purchase_description = (
                                    product.description_purchase or ""
                                )
                                if (
                                    not product_supplierinfo.product_code
                                    and not product_supplierinfo.product_name
                                ):
                                    temp = elem.get("item")

                                elif (
                                    product_supplierinfo.product_code
                                    and not product_supplierinfo.product_name
                                ):
                                    temp = "[%s] %s" % (
                                        product_supplierinfo.product_code,
                                        elem.get("item"),
                                    )

                                elif (
                                    product_supplierinfo.product_code
                                    and product_supplierinfo.product_name
                                ):
                                    temp = "[%s] %s" % (
                                        product_supplierinfo.product_code,
                                        product_supplierinfo.product_name,
                                    )

                                else:
                                    temp = product_supplierinfo.product_name
                                product_name = f"{temp}\n{purchase_description}"
                            else:
                                # SG - 01/03/2024: assign the correct product name based on description_purchase (English as the language)
                                purchase_description = (
                                    product.description_purchase or ""
                                )
                                product_name = (
                                    f"{elem.get('item')}\n{purchase_description}"
                                )

                            po_line = proc_orderline.create(
                                {
                                    "order_id": supplier_reference[supplier_id]["id"],
                                    "product_id": int(item_id),
                                    "product_qty": quantity,
                                    "product_uom": int(uom_id),
                                    "date_planned": date_planned,
                                    "price_unit": price_unit,
                                    "name": product_name,
                                }
                            )
                            product_supplier_dict[(item_id, supplier_id)] = po_line

                        else:
                            po_line = product_supplier_dict[(item_id, supplier_id)]
                            po_line.date_planned = min(
                                po_line.date_planned,
                                date_planned,
                            )
                            po_line.product_qty = po_line.product_qty + float(quantity)
                        countproc += 1
                    elif ordertype == "DO":
                        if not hasattr(self, "do_index"):
                            self.do_index = 0
                        self.do_index += 1
                        product = self.env["product.product"].browse(int(item_id))
                        quantity = elem.get("quantity")
                        date_shipping = elem.get("start")
                        origin = elem.get("origin")
                        destination = elem.get("destination")
                        if origin == "Ohio" and destination == "Castle Rock":
                            picking_type_id = 47
                            location_id = 21
                            location_dest_id = 25
                        elif origin == "Castle Rock" and destination == "Ohio":
                            picking_type_id = 48
                            location_id = 8
                            location_dest_id = 12
                        elif origin == "Castle Rock" and destination == "Elbert":
                            picking_type_id = 89
                            location_id = 8
                            location_dest_id = 12
                        elif origin == "Elbert" and destination == "Castle Rock":
                            picking_type_id = 87
                            location_id = 11950
                            location_dest_id = 11953
                        else:
                            # ignore this DO
                            logger.warning(
                                "Skipping DO creation as only Castle Rock and Ohio are accepted"
                            )
                            continue
                        if date_shipping:
                            date_shipping = datetime.strptime(
                                date_shipping, "%Y-%m-%d %H:%M:%S"
                            )
                        else:
                            date_shipping = datetime.now()
                        if not hasattr(self, "stock_picking_dict"):
                            self.stock_picking_dict = {}
                        sp = self.stock_picking_dict.get((origin, destination))
                        if sp is None:
                            sp = stck_picking.create(
                                {
                                    "picking_type_id": picking_type_id,
                                    "scheduled_date": date_shipping,
                                    "location_id": location_id,
                                    "location_dest_id": location_dest_id,
                                    "move_type": "direct",
                                    "origin": "frePPLe",
                                }
                            )
                            self.stock_picking_dict[(origin, destination)] = sp
                        if not hasattr(self, "sm_dict"):
                            self.sm_dict = {}
                        sm = self.sm_dict.get((product.id, sp.id))
                        if sm:
                            sm.write(
                                {
                                    "date": min(date_shipping, sm.date),
                                    "product_uom_qty": sm.product_uom_qty
                                    + float(quantity),
                                }
                            )
                        else:
                            sm = stck_move.create(
                                {
                                    "date": date_shipping,
                                    "product_id": product.id,
                                    "product_uom_qty": quantity,
                                    "product_uom": int(uom_id),
                                    "location_id": sp.location_id.id,
                                    "location_dest_id": sp.location_dest_id.id,
                                    "picking_id": sp.id,
                                    "origin": "frePPLe",
                                    "name": "%s %s"
                                    % (
                                        self.stock_picking_dict.get(
                                            (origin, destination)
                                        ).name,
                                        self.do_index,
                                    ),
                                }
                            )
                            self.sm_dict[(product.id, sp.id)] = sm
                    elif ordertype == "WO":
                        # Update a workorder
                        if elem.get("owner") in mo_references:
                            # Newly created MO
                            mo = mo_references[elem.get("owner")]
                        else:
                            # Existing MO
                            mo = mfg_order.search([("name", "=", elem.get("owner"))])
                        if mo:
                            wo_list = mfg_workorder.search(
                                [
                                    ("production_id", "=", mo.id),
                                    ("state", "in", ["pending", "waiting", "ready"]),
                                ]
                            )
                            for wo in wo_list:
                                if wo["display_name"] != elem.get("operation"):
                                    # Can't filter on the computed display_name field in the search...
                                    continue
                                if wo:
                                    wo.write(
                                        {
                                            "date_planned_start": self.timezone.localize(
                                                datetime.strptime(
                                                    elem.get("start"),
                                                    "%Y-%m-%d %H:%M:%S",
                                                )
                                            )
                                            .astimezone(UTC)
                                            .replace(tzinfo=None),
                                            "date_planned_finished": self.timezone.localize(
                                                datetime.strptime(
                                                    elem.get("end"),
                                                    "%Y-%m-%d %H:%M:%S",
                                                )
                                            )
                                            .astimezone(UTC)
                                            .replace(tzinfo=None),
                                        }
                                    )
                                    break
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
                        actual_user_context = None
                        if self.actual_user:
                            actual_user_context = dict(
                                self.env["res.users"]
                                .with_user(self.actual_user)
                                .context_get()
                            )
                            actual_user_context.update(
                                {
                                    "default_picking_type_id": picking.id,
                                }
                            )
                        else:
                            self.env.context = dict(self.env.context)
                            self.env.context.update(
                                {
                                    "default_picking_type_id": picking.id,
                                }
                            )

                        mo = mfg_order.with_context(
                            actual_user_context or self.env.context
                        ).create(
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

                        # Process the workorder information we received
                        if wo_data:
                            for wo in mo.workorder_ids:
                                for rec in wo_data:
                                    if rec["id"] == wo.operation_id.id:
                                        for res in rec["workcenters"]:
                                            if res["id"] != wo.workcenter_id.id:
                                                wc = mfg_workcenter.browse(res["id"])
                                                if wo.workcenter_id == wc[0].owner:
                                                    wo.workcenter_id = res["id"]

                        countmfg += 1
                except Exception as e:
                    logger.error("Exception %s" % e)
                    msg.append(str(e))
                # Remove the element now to keep the DOM tree small
                wo_data = []
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
