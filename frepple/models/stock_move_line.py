import os
import logging
from odoo import models, api, fields

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    frepple_reference = fields.Char('Reference (frePPLe)')
