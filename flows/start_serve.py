from prefect import serve
import sys

from flows.order_cancel_flow import order_cancel_flow

sys.path.append('..')
sys.path.append('.')

from flows.open_long_potition import open_long_position
from flows.order_filled_flow import order_filled_flow

filled_depl = order_filled_flow.to_deployment(name='order_filled_flow')
open_long_depl = open_long_position.to_deployment(name='open_long_position')
cancel_depl = order_cancel_flow(name='order_cancel_flow')
serve(filled_depl, open_long_depl, cancel_depl)
