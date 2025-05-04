DOMAIN = "pstryk"
API_URL = "https://api.pstryk.pl/integrations/"
API_TIMEOUT = 30

BUY_ENDPOINT = "pricing/?resolution=hour&window_start={start}&window_end={end}"
SELL_ENDPOINT = "prosumer-pricing/?resolution=hour&window_start={start}&window_end={end}"
ENERGY_USAGE_ENDPOINT = "meter-data/energy-usage/?for_tz=Europe%2FWarsaw&resolution=day&window_end={end}&window_start={start}"

ATTR_BUY_PRICE = "buy_price"
ATTR_SELL_PRICE = "sell_price"
ATTR_HOURS = "hours"
