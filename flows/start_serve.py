from prefect import serve
import sys

sys.path.append('..')
sys.path.append('.')

from flows.order_cancel_flow import order_cancel_flow
from flows.order_new_flow import order_new_flow
from flows.order_filled_flow import order_filled_flow
from flows.positions_flow import open_long_position, close_positions

filled_depl = order_filled_flow.to_deployment(name='order_filled_flow')
cancel_depl = order_cancel_flow.to_deployment(name='order_cancel_flow')
new_depl = order_new_flow.to_deployment(name='order_new_flow')
open_long_depl = open_long_position.to_deployment(name='open_long_position')
close_positions_depl = close_positions.to_deployment(name='close_positions')
serve(filled_depl, cancel_depl, new_depl, open_long_depl, close_positions_depl)

#  order-filled-flow/order_filled_flow   │
# │ order-cancel-flow/order_cancel_flow   │
# │ order-new-flow/order_new_flow         │
# │ open-long-position/open_long_position │
# │ close-positions/close_positions
