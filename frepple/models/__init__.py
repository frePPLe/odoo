from . import res_company
from . import res_config_settings
from . import stock_move_line
from . import product_supplierinfo_inherit

with_mrp = True
if with_mrp:
    from . import mrp_skill
    from . import mrp_workcenter_inherit
    from . import mrp_routing_workcenter_inherit
    from . import mrp_workcenter_skill
