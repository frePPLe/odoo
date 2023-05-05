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

import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class WorkOrderInherit(models.Model):
    _inherit = "mrp.workorder"

    secondary_workcenters = fields.One2many(
        "mrp.workorder.secondary.workcenter",
        "workorder_id",
        required=False,
        copy=True,
        help="Extra workcenters needed for this work order",
    )

    def assign_secondary_work_centers(self):
        """
        Logic to assign secondary work centers:
        - if the work center has no children:
            create wo_sec_line record for this workcenter
        - else if its a tool and another wo of this mo uses a secondary workcenter already of same group:
            use the same secondary as the other work order
        - else if a skill is required:
            find child a child resource that has the correct skill, ordered by priority
        - else:
            take the first child, ordered by name
        """
        for x in self.operation_id.secondary_workcenter:

            # store the ids of the workcenters having that secondary workcenter as owner
            children = [
                i.id
                for i in self.env["mrp.workcenter"].search(
                    [("owner", "=", x.workcenter_id.id)], order="name"
                )
            ]

            selectedWorkCenter = None
            if not children:
                selectedWorkCenter = x.workcenter_id.id

            if not selectedWorkCenter and (
                x.workcenter_id.tool
                or self.env["mrp.workcenter"].search_count(
                    [("owner", "=", x.workcenter_id.id), ("tool", "=", True)]
                )
                > 0
            ):
                # check if another wo of the same MO already has a tool workcenter
                for wo in self.production_id.workorder_ids:
                    if wo.id == self.id:
                        continue
                    for sw in wo.secondary_workcenters:
                        if sw.workcenter_id.id in children:
                            selectedWorkCenter = sw.workcenter_id.id
                            break
                    if selectedWorkCenter:
                        break

            if not selectedWorkCenter:
                if x.skill and x.skill.id:
                    # Find workcenters with the required skill
                    valid_workcenters = (
                        self.env["mrp.workcenter.skill"]
                        .search(
                            [("skill", "=", x.skill.id)],
                            order="priority",
                        )
                        .read(["id", "workcenter"])
                    )
                    for v in valid_workcenters[:]:
                        if v["workcenter"][0] in children:
                            # add the secondary record with the top priority workcenter
                            selectedWorkCenter = v["workcenter"][0]
                            break
                    if not selectedWorkCenter:
                        _logger.warning(
                            "couldn't find a valid secondary work center with %s skill"
                            % (x.skill.name,)
                        )
                else:
                    # no skills, pick the first child
                    selectedWorkCenter = children[0]

            if selectedWorkCenter:
                self.env["mrp.workorder.secondary.workcenter"].create(
                    [
                        {
                            "workorder_id": self.id,
                            "workcenter_id": selectedWorkCenter,
                            "duration": x.duration * self.qty_production,
                        }
                    ]
                )
        return True

    @api.model_create_multi
    def create(self, vals_list):
        wo_list = super().create(vals_list)
        if not self.env.context.get("ignore_secondary_workcenters", False):
            for wo in wo_list:
                wo.assign_secondary_work_centers()
            return wo_list
