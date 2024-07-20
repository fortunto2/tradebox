from prefect import serve
import sys
sys.path.append('..')
sys.path.append('.')

from flows.open_long_potition import open_long_position
from flows.order_filled_flow import order_filled_flow

filled_depl = order_filled_flow.to_deployment(name='order_filled_flow')
open_long_depl = open_long_position.to_deployment(name='open_long_position')
serve(filled_depl, open_long_depl)
