# -*- coding: utf-8 -*-
#
# Copyright (C) 2022 by frePPLe bv
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


class SecondaryWorkcenter(models.Model):
    _name = "mrp.secondary.workcenter"
    _description = "List of workcenter skill associations"
    _rec_name = "workcenter_id"

    routing_workcenter_id = fields.Many2one(
        "mrp.routing.workcenter",
        "Parent routing workcenter",
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
    skill = fields.Many2one("mrp.skill", "Skill", required=False)
    search_mode = fields.Selection(
        [
            ("PRIORITY", "priority"),
            ("MINCOST", "minimum cost"),
            ("MINPENALTY", "minimum penalty"),
            ("MINCOSTPENALTY", "minimum cost plus penalty"),
        ],
        string="Search Mode",
        required=False,
        default="PRIORITY",
    )
    priority = fields.Integer("priority", default=1)
    duration = fields.Float("Duration", help="time in minutes")
