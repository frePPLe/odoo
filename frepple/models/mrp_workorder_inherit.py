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
        _logger.error(
            "CALLING IT %s %s %s" % (self, self.production_id, self.operation_id)
        )
        for x in self.operation_id.secondary_workcenter:
            _logger.error(
                "     secondary %s" % (self.operation_id.secondary_workcenter)
            )
            # if no children:
            #     create wo_sec_line record for this workcenter
            # elif its a tool and another wo of this mo uses a secondary workcenter already of same group:
            #     use the same secondary
            # else:
            #     find child a child resource that has the correct skill, order by priority
            # create wo_sec_line record for this workcenter

    @api.model_create_multi
    def create(self, vals_list):
        wo_list = super().create(vals_list)
        for wo in wo_list:
            self.assign_secondary_work_centers()
        return wo_list
