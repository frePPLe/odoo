# -*- coding: utf-8 -*-
#
# Copyright (C) 2023 by frePPLe bv
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
from odoo import models, fields


class WorkorderSecondaryWorkcenter(models.Model):
    _name = "mrp.workorder.secondary.workcenter"
    _description = "Secondary workcenter of a work order"
    _rec_name = "workcenter_id"

    workorder_id = fields.Many2one(
        "mrp.workorder",
        "Parent work order",
        index=True,
        ondelete="cascade",
        required=True,
    )
    workcenter_id = fields.Many2one(
        "mrp.workcenter",
        "Work Center",
        required=True,
        ondelete="cascade",
    )
    duration = fields.Float("Duration", help="time in minutes")
