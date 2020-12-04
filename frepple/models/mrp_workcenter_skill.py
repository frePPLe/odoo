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
import time

from odoo import api, models, fields, exceptions

_logger = logging.getLogger(__name__)



class WorkcenterSkill(models.Model):
    _name = "mrp.workcenter.skill"
    _description="List of workcenter skill associations"

    workcenter = fields.Many2one("mrp.workcenter", "Work Center", required=True)
    skill = fields.Many2one("mrp.skill", "Skill", required=True)
    priority = fields.Integer("priority", default=1)
