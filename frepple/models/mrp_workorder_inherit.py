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

    # if no children:
    #     create wo_sec_line record for this workcenter
    # elif its a tool and another wo of this mo uses a secondary workcenter already of same group:
    #     use the same secondary
    # else:
    #     find child a child resource that has the correct skill, order by priority
    # create wo_sec_line record for this workcenter
    def assign_secondary_work_centers(self):

        for x in self.operation_id.secondary_workcenter:

            # store the ids of the workcenters having that secondary workcenter as owner
            children = [
                i.id
                for i in self.env["mrp.workcenter"].search(
                    [("owner", "=", x.workcenter_id.id)], order="name"
                )
            ]

            if len(children) == 0:
                self.env["mrp.workorder.secondary.workcenter"].create(
                    [
                        {
                            "workorder_id": self.id,
                            "workcenter_id": x.workcenter_id.id,
                            "duration": x.duration * self.qty_production,
                        }
                    ]
                )
            elif (
                x.workcenter_id.tool
                or self.env["mrp.workcenter"].search_count(
                    [("owner", "=", x.workcenter_id.id), ("tool", "=", True)]
                )
                > 0
            ):
                # check if another wo of the same MO already has a tool workcenter
                tool = None
                for wo in self.production_id.workorder_ids:
                    if wo.id == self.id:
                        continue
                    for sw in wo.secondary_workcenters:
                        if sw.workcenter_id.id in children:
                            tool = sw.workcenter_id.id
                            break
                if tool:
                    self.env["mrp.workorder.secondary.workcenter"].create(
                        [
                            {
                                "workorder_id": self.id,
                                "workcenter_id": tool,
                                "duration": x.duration * self.qty_production,
                            }
                        ]
                    )
                else:
                    if x.skill:
                        Found = False
                        for res_skill in self.env["mrp.workcenter.skill"].search(
                            [("workcenter.id", "in", children)]
                        ):
                            if res_skill.skill.id == x.skill.id:
                                self.env["mrp.workorder.secondary.workcenter"].create(
                                    [
                                        {
                                            "workorder_id": self.id,
                                            "workcenter_id": res_skill.workcenter.id,
                                            "duration": x.duration
                                            * self.qty_production,
                                        }
                                    ]
                                )
                                Found = True
                                break
                        if not Found:
                            _logger.warning(
                                "couldn't find a valid secondary work center with %s skill"
                                % (x.skill.name,)
                            )

                    else:
                        # no skills, pick the first one
                        self.env["mrp.workorder.secondary.workcenter"].create(
                            [
                                {
                                    "workorder_id": self.id,
                                    "workcenter_id": children[0],
                                    "duration": x.duration * self.qty_production,
                                }
                            ]
                        )

            else:
                # Does the secondary workcenter require a skill
                if x.skill and x.skill.id:
                    # Find workcenters with the same skill
                    valid_workcenters = (
                        self.env["mrp.workcenter.skill"]
                        .search(
                            [("skill", "=", x.skill.id)],
                            order="priority",
                        )
                        .read(["id", "workcenter"])
                    )

                    # Remove workcenters that are not in the children list
                    for v in valid_workcenters[:]:
                        if v["workcenter"][0] not in children:
                            valid_workcenters.remove(v)

                    # add the secondary record with the top priority workcenter
                    if len(valid_workcenters) > 0:
                        self.env["mrp.workorder.secondary.workcenter"].create(
                            [
                                {
                                    "workorder_id": self.id,
                                    "workcenter_id": valid_workcenters[0]["workcenter"][
                                        0
                                    ],
                                    "duration": x.duration * self.qty_production,
                                }
                            ]
                        )
                else:
                    # no skills, pick the first one
                    self.env["mrp.workorder.secondary.workcenter"].create(
                        [
                            {
                                "workorder_id": self.id,
                                "workcenter_id": children[0],
                                "duration": x.duration * self.qty_production,
                            }
                        ]
                    )

    @api.model_create_multi
    def create(self, vals_list):
        wo_list = super().create(vals_list)
        for wo in wo_list:
            wo.assign_secondary_work_centers()
        return wo_list
