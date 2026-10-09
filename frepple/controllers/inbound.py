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
import json
import logging
from xml.etree.cElementTree import iterparse
from datetime import datetime
from pytz import timezone, UTC

logger = logging.getLogger(__name__)


class importer(object):
    def __init__(
        self, req, database=None, company=None, mode=1, disclose_stack_trace=False
    ):
        self.env = req.env
        self.database = database
        self.company = company
        self.datafile = req.httprequest.files.get("frePPLe plan")
        self.disclose_stack_trace = disclose_stack_trace

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

        # Pick up the timezone of the connector user (or UTC if not set)
        try:
            usr = self.env["res.users"].browse(ids=[req.uid]).read(["tz"])[0]
            self.timezone = timezone(usr["tz"] or "UTC")
        except Exception:
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
            product_product = self.env["product.product"].with_user(self.actual_user)
            product_supplierinfo = self.env["product.supplierinfo"].with_user(
                self.actual_user
            )
            uom_uom = self.env["uom.uom"].with_user(self.actual_user)
            proc_order = self.env["purchase.order"].with_user(self.actual_user)
            proc_orderline = self.env["purchase.order.line"].with_user(self.actual_user)
            mfg_order = self.env["mrp.production"].with_user(self.actual_user)
            mfg_workorder = self.env["mrp.workorder"].with_user(self.actual_user)
            mfg_workcenter = self.env["mrp.workcenter"].with_user(self.actual_user)
            mfg_workorder_secondary = self.env[
                "mrp.workorder.secondary.workcenter"
            ].with_user(self.actual_user)
            stck_picking_type = self.env["stock.picking.type"].with_user(
                self.actual_user
            )
            bom_type = self.env["mrp.bom"].with_user(self.actual_user)
            procurement_group = self.env["procurement.group"].with_user(
                self.actual_user
            )
            stock_route = self.env["stock.route"].with_user(self.actual_user)
            stock_warehouse = self.env["stock.warehouse"].with_user(self.actual_user)
            change_product_qty = self.env["change.production.qty"].with_user(
                self.actual_user
            )
            hasRequisition = True
            try:
                purchase_requisition = self.env["purchase.requisition"].with_user(
                    self.actual_user
                )
                purchase_requisition_line = self.env[
                    "purchase.requisition.line"
                ].with_user(self.actual_user)
            except:
                hasRequisition = False
        else:
            product_product = self.env["product.product"]
            product_supplierinfo = self.env["product.supplierinfo"]
            uom_uom = self.env["uom.uom"]
            proc_order = self.env["purchase.order"]
            proc_orderline = self.env["purchase.order.line"]
            mfg_order = self.env["mrp.production"]
            mfg_workorder = self.env["mrp.workorder"]
            mfg_workcenter = self.env["mrp.workcenter"]
            mfg_workorder_secondary = self.env["mrp.workorder.secondary.workcenter"]
            stck_picking_type = self.env["stock.picking.type"]
            procurement_group = self.env["procurement.group"]
            stock_route = self.env["stock.route"]
            stock_warehouse = self.env["stock.warehouse"]
            change_product_qty = self.env["change.production.qty"]
            hasRequisition = True
            try:
                purchase_requisition = self.env["purchase.requisition"]
                purchase_requisition_line = self.env["purchase.requisition.line"]
            except:
                hasRequisition = False
        if self.mode == 1:
            # Cancel previous draft purchase quotations
            m = self.env["purchase.order"]
            recs = m.search(
                [
                    ("state", "=", "draft"),
                    ("origin", "=like", "frePPLe%"),
                    ("company_id", "=", self.company.id),
                ]
            )
            recs.write({"state": "cancel"})
            recs.unlink()
            msg.append("Removed %s old draft purchase orders" % len(recs))

            # Cancel previous draft manufacturing orders
            recs = mfg_order.search(
                [
                    "|",
                    ("state", "=", "draft"),
                    ("state", "=", "cancel"),
                    ("origin", "=like", "frePPLe%"),
                    ("company_id", "=", self.company.id),
                ]
            )
            recs.write({"state": "cancel"})
            recs.unlink()
            msg.append("Removed %s old draft manufacturing orders" % len(recs))

            # read all the blanket orders
            if hasRequisition:
                pr_ids = [
                    i
                    for i in purchase_requisition.search(
                        [
                            "&",
                            "&",
                            "|",
                            ("date_end", "=", False),
                            ("date_end", ">=", datetime.now()),
                            ("requisition_type", "=", "blanket_order"),
                            ("state", "=", "confirmed"),
                        ]
                    )
                ]
                requisition_dic = {
                    (i.product_id.id, i.requisition_id.vendor_id.id): i.requisition_id
                    for i in purchase_requisition_line.search(
                        [
                            ("requisition_id", "in", [j.id for j in pr_ids]),
                        ]
                    )
                }

        # Parsing the XML data file
        countproc = 0
        countmfg_created = 0
        countmfg_updated = 0

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

        # Mapping between frepple-generated DO reference and the created odoo picking ids
        do_references = {}

        # Workcenters of a workorder to update
        resources = []

        context = (
            dict(self.env["res.users"].with_user(self.actual_user).context_get())
            if self.actual_user
            else dict(self.env.context)
        )

        for event, elem in iterparse(self.datafile, events=("start", "end")):
            if (
                elem.tag == "operationplan"
                and elem.get("ordertype") == "WO"
                and event == "start"
            ):
                resources = []
            elif elem.tag == "resource" and event == "end":
                resources.append(elem.get("id"))
            if event == "start" and elem.tag == "workorder" and elem.get("operation"):
                try:
                    wo = {
                        "operation": elem.get("operation"),
                        "id": int(elem.get("operation").rsplit("- ", 1)[-1]),
                    }
                    st = elem.get("start")
                    if st:
                        try:
                            wo["start"] = (
                                self.timezone.localize(
                                    datetime.strptime(
                                        st,
                                        "%Y-%m-%d %H:%M:%S",
                                    )
                                )
                                .astimezone(UTC)
                                .replace(tzinfo=None)
                            )
                        except Exception:
                            pass
                    nd = elem.get("end")
                    if st:
                        try:
                            wo["end"] = (
                                self.timezone.localize(
                                    datetime.strptime(
                                        nd,
                                        "%Y-%m-%d %H:%M:%S",
                                    )
                                )
                                .astimezone(UTC)
                                .replace(tzinfo=None)
                            )
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

                        supplier_id = int(elem.get("supplier").rsplit(" ", 1)[-1])
                        quantity = float(elem.get("quantity"))
                        date_planned = elem.get("end")
                        if date_planned:
                            date_planned = (
                                self.timezone.localize(
                                    datetime.strptime(
                                        date_planned,
                                        "%Y-%m-%d %H:%M:%S",
                                    )
                                )
                                .astimezone(UTC)
                                .replace(tzinfo=None)
                            )
                        date_ordered = elem.get("start")
                        if date_ordered:
                            date_ordered = (
                                self.timezone.localize(
                                    datetime.strptime(
                                        date_ordered,
                                        "%Y-%m-%d %H:%M:%S",
                                    )
                                )
                                .astimezone(UTC)
                                .replace(tzinfo=None)
                            )

                        # Is that an update of an existing PO ?
                        status = elem.get("status")
                        if status in ("approved", "confirmed"):
                            po_line_id = int(elem.get("id").rsplit(" - ", 1)[-1])
                            po_line = proc_orderline.browse(po_line_id)
                            if po_line:
                                po_line.write(
                                    {
                                        "product_id": int(item_id),
                                        "product_qty": quantity,
                                        "product_uom": int(uom_id),
                                        "date_planned": date_planned,
                                        "name": elem.get("item"),
                                    }
                                )
                                countproc += 1
                            else:
                                logger.error(
                                    "Unable to find PO line %s in Odoo"
                                    % (elem.get("reference"),)
                                )
                            continue

                        # Create purchase order
                        remark = elem.get("remark", None)
                        if remark:
                            remark = "frePPLe - %s" % remark
                        else:
                            remark = "frePPLe"
                        if supplier_id not in supplier_reference:
                            po_args = {
                                "company_id": self.company.id,
                                "partner_id": supplier_id,
                                "origin": remark,
                            }
                            try:
                                picking_type_id = stck_picking_type.search(
                                    [
                                        ("code", "=", "incoming"),
                                        (
                                            "warehouse_id",
                                            "=",
                                            int(elem.get("location_id")),
                                        ),
                                    ],
                                    limit=1,
                                )[:1]
                                if not picking_type_id:
                                    picking_type_id = stck_picking_type.search(
                                        [
                                            ("code", "=", "incoming"),
                                            ("warehouse_id", "=", False),
                                        ],
                                        limit=1,
                                    )[:1]
                                if picking_type_id:
                                    po_args["picking_type_id"] = picking_type_id.id
                            except Exception:
                                pass
                            po = proc_order.create(po_args)
                            po.payment_term_id = (
                                po.partner_id.property_supplier_payment_term_id.id
                            )
                            supplier_reference[supplier_id] = {
                                "id": po.id,
                                "min_planned": date_planned,
                                "min_ordered": date_ordered,
                                "po": po,
                                "frepple_references": [elem.get("id")],
                            }
                        else:
                            supplier_reference[supplier_id][
                                "frepple_references"
                            ].append(elem.get("id"))
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
                            product = product_product.browse(int(item_id))
                            # look first for a record for that specific variant/product
                            supplier = product_supplierinfo.search(
                                [
                                    "&",
                                    ("partner_id", "=", supplier_id),
                                    (
                                        "product_id",
                                        "=",
                                        product.id,
                                    ),
                                    ("min_qty", "<=", quantity),
                                ],
                                limit=1,
                                order="min_qty desc",
                            )
                            # if no record found then move at template level
                            if not supplier:
                                supplier = product_supplierinfo.search(
                                    [
                                        "&",
                                        ("partner_id", "=", supplier_id),
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
                            product_uom = uom_uom.browse(int(uom_id))
                            # first create a minimal PO line
                            po_line = proc_orderline.create(
                                {
                                    "order_id": supplier_reference[supplier_id]["id"],
                                    "product_id": int(item_id),
                                    "product_qty": quantity,
                                    "product_uom": int(uom_id),
                                }
                            )
                            po = po_line.order_id
                            # set the PO currency.
                            # By default Odoo sets the company currency for the PO currency
                            # which can be different from the vendor currency
                            if (
                                supplier
                                and supplier.currency_id
                                and supplier.currency_id.id != po.currency_id.id
                            ):
                                po.currency_id = supplier.currency_id.id

                            # Is there a blanket order for this product /supplier ?
                            if (
                                self.mode == 1
                                and hasRequisition
                                and not po_line.order_id.requisition_id
                                and (int(item_id), supplier_id) in requisition_dic
                            ):
                                po.requisition_id = requisition_dic[
                                    (int(item_id), supplier_id)
                                ]
                            elif (
                                self.mode != 1
                                and hasRequisition
                                and not po_line.order_id.requisition_id
                            ):
                                for i in purchase_requisition_line.search(
                                    [
                                        "&",
                                        "&",
                                        "&",
                                        "&",
                                        "|",
                                        ("requisition_id.date_end", "=", False),
                                        (
                                            "requisition_id.date_end",
                                            ">=",
                                            datetime.now(),
                                        ),
                                        (
                                            "requisition_id.requisition_type",
                                            "=",
                                            "blanket_order",
                                        ),
                                        ("requisition_id.state", "=", "confirmed"),
                                        ("product_id.id", "=", int(item_id)),
                                        (
                                            "requisition_id.vendor_id.id",
                                            "=",
                                            supplier_id,
                                        ),
                                    ],
                                    limit=1,
                                ):
                                    po_line.order_id.requisition_id = i.requisition_id

                            # Then let odoo computes all the fields (taxes, name, description...)

                            d = po_line._prepare_purchase_order_line(
                                product,
                                quantity,
                                product_uom,
                                self.company,
                                supplier,
                                po,
                            )
                            d["date_planned"] = date_planned
                            # Finally update the PO line
                            po_line.write(d)

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
                    elif ordertype == "DO":
                        reference = elem.get("reference")
                        product = product_product.browse(int(item_id))
                        quantity = float(elem.get("quantity"))
                        date_shipping = elem.get("start")
                        date_receiving = elem.get("end")
                        destination_id = int(elem.get("destination_id"))
                        route_id = int(elem.get("route_id"))
                        if (
                            not product
                            or not quantity
                            or not date_shipping
                            or not destination_id
                            or not route_id
                        ):
                            continue

                        date_shipping, date_receiving = (
                            (
                                self.timezone.localize(
                                    datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
                                )
                                .astimezone(UTC)
                                .replace(tzinfo=None)
                                if d
                                else False
                            )
                            for d in (date_shipping, date_receiving)
                        )

                        # see if the connectors received the route to use
                        selected_route = stock_route.browse(route_id)

                        product_uom = uom_uom.browse(int(uom_id))

                        # 1. Create a procurement group
                        pg = procurement_group.create(
                            {
                                "name": "Frepple",
                                "move_type": "direct",  # or 'one'
                            }
                        )

                        # 2. Define the Procurement
                        procurement = procurement_group.Procurement(
                            product,
                            quantity,
                            product_uom,
                            stock_warehouse.browse(
                                destination_id
                            ).lot_stock_id,  # location_id
                            product.display_name,  # name
                            pg.name,  # origin
                            self.company,  # company_id
                            {
                                "route_ids": selected_route,
                                "warehouse_id": stock_warehouse.browse(destination_id),
                                "date_planned": date_shipping,
                                "date_deadline": date_receiving,
                                "group_id": pg,  # Ties rules & moves to this group
                            },
                        )

                        # 3. Run the procurement engine of Odoo to generate the pickings
                        procurement_group.run([procurement])

                        # 4. Retrieve created pickings via the procurement group
                        pickings = self.env["stock.picking"].search(
                            [("group_id", "=", pg.id)]
                        )

                        if pickings:
                            do_references[reference] = ", ".join(
                                pickings.mapped("name")
                            )

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
                                if wo["display_name"] != elem.get("reference"):
                                    # Can't filter on the computed display_name field in the search...
                                    continue
                                if wo:
                                    data = {
                                        "date_start": self.timezone.localize(
                                            datetime.strptime(
                                                elem.get("start"),
                                                "%Y-%m-%d %H:%M:%S",
                                            )
                                        )
                                        .astimezone(UTC)
                                        .replace(tzinfo=None),
                                        "date_finished": self.timezone.localize(
                                            datetime.strptime(
                                                elem.get("end"),
                                                "%Y-%m-%d %H:%M:%S",
                                            )
                                        )
                                        .astimezone(UTC)
                                        .replace(tzinfo=None),
                                    }
                                    for res_id in resources:
                                        res = mfg_workcenter.search(
                                            [("id", "=", res_id)]
                                        )
                                        if not res:
                                            continue
                                        if (
                                            not wo.operation_id  # No operation defined
                                            or (
                                                wo.operation_id.workcenter_id
                                                == res  # Same workcenter
                                                or (
                                                    # New member of a pool
                                                    wo.operation_id.workcenter_id
                                                    and wo.operation_id.workcenter_id
                                                    == res.owner
                                                )
                                            )
                                        ):
                                            # Change primary work center
                                            data["workcenter_id"] = res.id
                                        else:
                                            # Check assigned secondary resources
                                            for sec in wo.secondary_workcenters:
                                                if sec.workcenter_id.owner == res:
                                                    break
                                                if sec.workcenter_id.owner == res.owner:
                                                    # Change secondary work center
                                                    sec.write({"workcenter_id": res.id})
                                                    break
                                    wo.write(data)
                                    break
                    else:
                        # Create or update a manufacturing order
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
                        # Also do not create secondary work center records
                        context.update(
                            {
                                "default_picking_type_id": picking.id,
                                "ignore_secondary_workcenters": True,
                            }
                        )
                        if (elem.get("status") or "proposed") == "proposed":
                            # MO creation
                            remark = elem.get("remark", None)
                            if remark:
                                remark = "frePPLe - %s" % remark
                            else:
                                remark = "frePPLe"
                            bom_id = int(elem.get("operation").rsplit(" ", 1)[1])
                            try:
                                bom = bom_type.search(
                                    [
                                        ("id", "=", bom_id),
                                    ],
                                    limit=1,
                                )
                                if not bom or bom.type == "phantom":
                                    # Avoid creating MO on a) non-existing BOMs and b) phantom/kit BOMs
                                    continue
                            except Exception:
                                pass
                            mo = mfg_order.with_context(context).create(
                                {
                                    "product_qty": elem.get("quantity"),
                                    "date_start": elem.get("start"),
                                    "date_finished": elem.get("end"),
                                    "product_id": int(item_id),
                                    "company_id": self.company.id,
                                    "product_uom_id": int(uom_id),
                                    "picking_type_id": picking.id,
                                    "bom_id": bom_id,
                                    "qty_producing": 0.00,
                                    # TODO no place to store the criticality
                                    # elem.get('criticality'),
                                    "origin": remark,
                                }
                            )
                            countmfg_created += 1
                            # Remember odoo name for the MO reference passed by frepple.
                            # This mapping is later used when importing WO.
                            mo_references[elem.get("reference")] = mo
                            mo._create_update_move_finished()
                            # mo.action_confirm()  # confirm MO
                            create = True
                        else:
                            # MO update
                            create = False
                            try:
                                mo = mfg_order.with_context(context).search(
                                    [("name", "=", elem.get("reference"))]
                                )
                            except Exception:
                                continue
                            countmfg_updated += 1
                            if mo:
                                new_qty = float(elem.get("quantity"))
                                remark = elem.get("remark", None)
                                if remark:
                                    remark = "frePPLe - %s" % remark
                                else:
                                    remark = "frePPLe"
                                if mo.product_qty != new_qty:
                                    cpq = change_product_qty.create(
                                        {
                                            "mo_id": mo.id,
                                            "product_qty": new_qty,
                                        }
                                    )
                                    cpq.change_prod_qty()
                                arg_dict = {
                                    "date_start": elem.get("start"),
                                    "date_finished": elem.get("end"),
                                    "origin": remark,
                                }
                                # Odoo doesn't allow updating the start date of the MO if one WO is in progress
                                if any(
                                    wo.state == "progress" for wo in mo.workorder_ids
                                ):
                                    arg_dict.pop("date_start")
                                mo.write(arg_dict)
                                mo_references[elem.get("reference")] = mo

                        # Process the workorder information we received
                        if wo_data:
                            for wo in mo.workorder_ids:
                                for rec in wo_data:
                                    if (create and rec["id"] == wo.operation_id.id) or (
                                        not create and rec["id"] == wo.id
                                    ):
                                        # By default odoo populates the scheduled start date field only when you confirm and plan
                                        # the manufacturing order.
                                        # Here we are already updating it earlier
                                        # We need to update the end date first
                                        # if the new start date is after the current end date
                                        startUpdated = False
                                        if "start" in rec and (
                                            not wo.date_finished
                                            or rec["start"] <= wo.date_finished
                                        ):
                                            startUpdated = True
                                            wo.date_start = rec["start"]
                                            if not create:
                                                wo.write({"date_start": wo.date_start})
                                        if "end" in rec:
                                            wo.date_finished = rec["end"]
                                            if not create:
                                                wo.write(
                                                    {"date_finished": wo.date_finished}
                                                )
                                        if not startUpdated and "start" in rec:
                                            wo.date_start = rec["start"]
                                            if not create:
                                                wo.write({"date_start": wo.date_start})
                                        for res in rec.get("workcenters", []):
                                            wc = mfg_workcenter.browse(res["id"])
                                            if not wc:
                                                continue
                                            if create:
                                                if res["id"] != wo.workcenter_id.id:
                                                    if wo.workcenter_id == wc[0].owner:
                                                        wo.workcenter_id = res["id"]
                                                    else:
                                                        mfg_workorder_secondary.create(
                                                            {
                                                                "workcenter_id": res[
                                                                    "id"
                                                                ],
                                                                "workorder_id": wo.id,
                                                                "duration": res[
                                                                    "quantity"
                                                                ]
                                                                * wo.duration_expected,
                                                            }
                                                        )
                                            else:
                                                if (
                                                    not wo.operation_id  # No operation defined
                                                    or (
                                                        wo.operation_id.workcenter_id
                                                        == wc  # Same workcenter
                                                        or (
                                                            # New member of a pool
                                                            wo.operation_id.workcenter_id
                                                            and wo.operation_id.workcenter_id
                                                            == wc.owner
                                                        )
                                                    )
                                                ):
                                                    # Change primary work center
                                                    wo.write({"workcenter_id": wc.id})
                                                else:
                                                    # Check assigned secondary resources
                                                    for sec in wo.secondary_workcenters:
                                                        if (
                                                            sec.workcenter_id.owner
                                                            == wc
                                                        ):
                                                            break
                                                        if (
                                                            sec.workcenter_id.owner
                                                            == wc.owner
                                                        ):
                                                            # Change secondary work center
                                                            sec.write(
                                                                {"workcenter_id": wc.id}
                                                            )
                                                            break

                except Exception as e:
                    import traceback

                    logger.info(traceback.format_exc())
                    logger.error(f"Exception {e}")
                    if self.disclose_stack_trace:
                        msg.append(traceback.format_exc())
                    else:
                        msg.append(f"Exception {e}")
                # Remove the element now to keep the DOM tree small
                wo_data = []
                root.clear()
                # OPTIONAL SECTION: Store the planned delivery date (as computed by frepple) on odoo sales orders
                # elif event == "end" and elem.tag == "demand":
                #     try:
                #         deliverydate = (
                #             timezone(self.env.user.tz)
                #             .localize(
                #                 datetime.strptime(
                #                     elem.get("deliverydate"), "%Y-%m-%d %H:%M:%S"
                #                 ),
                #                 is_dst=None,
                #             )
                #             .astimezone(pytz.utc)
                #         ).strftime("%Y-%m-%d %H:%M:%S")
                #         sol_name = elem.get("name").rsplit(" ", 1)
                #         for so_line in self.env["sale.order.line"].search(
                #             [("id", "=", sol_name[1])], limit=1
                #         ):
                #             so_line.sale_delivery_date = (
                #                 datetime.strptime(deliverydate, "%Y-%m-%d %H:%M:%S")
                #             ).date()
                #             so_line.frepple_write_date = datetime.now()
                #             so_line.order_id._compute_commitment_date()
                #     except Exception as e:
                #         logger.error("Exception %s" % e)
                #         msg.append(str(e))
                # Remove the element now to keep the DOM tree small
                root.clear()
            elif event == "start" and elem.tag in ["operationplans", "demands"]:
                # Remember the root element
                root = elem

        # Update PO RFQ order_deadline and receipt date
        for sup in supplier_reference.values():
            if sup["min_planned"]:
                sup["po"].date_planned = sup["min_planned"]
            if sup["min_ordered"]:
                sup["po"].date_order = sup["min_ordered"]

        # Collect created PO/MO references
        created_pos = [
            {
                "reference": sup["po"].name,
                "id": sup["id"],
                "frepple_references": sup["frepple_references"],
            }
            for sup in supplier_reference.values()
        ]
        created_mos = [
            {"reference": mo.name, "id": mo.id, "frepple_reference": frepple_ref}
            for frepple_ref, mo in mo_references.items()
        ]
        created_dos = [
            {"reference": pickings, "id": pickings, "frepple_reference": frepple_ref}
            for frepple_ref, pickings in do_references.items()
        ]

        # Be polite, and reply to the post
        if countmfg_created:
            msg.append(
                "Created %d manufacturing orders%s"
                % (countmfg_created, "\n" if countmfg_updated or created_pos else "")
            )
        if countmfg_updated:
            msg.append(
                "Updated %d manufacturing orders%s"
                % (countmfg_updated, "\n" if created_pos else "")
            )
        if created_pos:
            msg.append("Created %d purchase orders" % (len(created_pos),))
        if created_dos:
            msg.append(
                "Created %d pickings"
                % (sum([len(v.split(",")) for v in do_references.values()]),)
            )
        return json.dumps(
            {
                "messages": msg,
                "created_purchase_orders": created_pos,
                "created_manufacturing_orders": created_mos,
                "created_distribution_orders": created_dos,
            }
        )
