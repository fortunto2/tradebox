# from decimal import Decimal
#
# from core.clients.sentry import sentry_sdk
# from prefect import flow, task
#
# from core.logger import logger
# from core.schemas.events.account_update import UpdateData
#
#
# @task
# def handle_account_update(event: UpdateData):
#     for position in event.positions:
#         if position.position_side == 'LONG':
#             long_position_qty = Decimal(position.position_amount)
#             long_entry_price = Decimal(position.breakeven_price)
#             logger.info(f'UPDATE Long PNL: {position.unrealized_pnl}')
#             logger.info(position)
#         elif position.position_side == 'SHORT':
#             short_position_qty = Decimal(position.position_amount)
#             short_entry_price = Decimal(position.breakeven_price)
#             logger.info(f'UPDATE Short PNL: {position.unrealized_pnl}')
#             logger.info(position)
#
#
# @flow
# def account_update_flow(event):
#     handle_account_update(event)
#     return event
