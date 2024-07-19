# Sentry Initialization
import sentry_sdk

sentry_sdk.init(
    dsn="https://c167125710805940a14cc72b74bf2617@o103263.ingest.us.sentry.io/4507614078238720",
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
)
