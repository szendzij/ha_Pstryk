"""Data update coordinator for Pstryk Energy integration."""
import logging
from datetime import timedelta, date # Added date
import asyncio
import aiohttp
import async_timeout
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util
# Import the new constant
from .const import API_URL, API_TIMEOUT, BUY_ENDPOINT, SELL_ENDPOINT, ENERGY_USAGE_ENDPOINT, DOMAIN

_LOGGER = logging.getLogger(__name__)

class ExponentialBackoffRetry:
    """Implementacja wykładniczego opóźnienia przy ponawianiu prób."""

    def __init__(self, max_retries=3, base_delay=2.0):
        """Inicjalizacja mechanizmu ponowień.

        Args:
            max_retries: Maksymalna liczba prób
            base_delay: Podstawowe opóźnienie w sekundach (zwiększane wykładniczo)
        """
        self.max_retries = max_retries
        self.base_delay = base_delay

    async def execute(self, func, *args, **kwargs):
        """Wykonaj funkcję z ponawianiem prób.

        Args:
            func: Funkcja asynchroniczna do wykonania
            args, kwargs: Argumenty funkcji

        Returns:
            Wynik funkcji

        Raises:
            UpdateFailed: Po wyczerpaniu wszystkich prób
        """
        last_exception = None
        for retry in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as err:
                last_exception = err
                # Nie czekamy po ostatniej próbie
                if retry < self.max_retries - 1:
                    delay = self.base_delay * (2 ** retry)
                    _LOGGER.debug(
                        "Retry %d/%d after error: %s (delay: %.1fs)",
                        retry + 1, self.max_retries, str(err), delay,
                    )
                    await asyncio.sleep(delay)

        # Jeśli wszystkie próby zawiodły
        # Wrap the original exception in UpdateFailed for coordinator handling
        raise UpdateFailed(f"Failed after {self.max_retries} retries: {last_exception}") from last_exception


def convert_price(value):
    """Convert price string to float."""
    try:
        return round(float(str(value).replace(",", ".").strip()), 2)
    except (ValueError, TypeError) as e:
        _LOGGER.warning("Price conversion error: %s", e)
        return None

class PstrykDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch price and energy data."""

    def __del__(self):
        """Properly clean up when object is deleted."""
        if hasattr(self, '_unsub_hourly') and self._unsub_hourly:
            self._unsub_hourly()
        if hasattr(self, '_unsub_midnight') and self._unsub_midnight:
            self._unsub_midnight()

    def __init__(self, hass, api_key, price_type):
        """Initialize the coordinator."""
        self.hass = hass
        self.api_key = api_key
        self.price_type = price_type # Keep price_type to determine which price endpoint to call
        self._unsub_hourly = None
        self._unsub_midnight = None
        self.retry_mechanism = ExponentialBackoffRetry()

        # Set a default update interval as a fallback (1 hour)
        update_interval = timedelta(hours=1)

        super().__init__(
            hass,
            _LOGGER,
            # Name can be more generic now or kept per price type if needed elsewhere
            name=f"{DOMAIN}_{price_type}_coordinator",
            update_interval=update_interval,
        )


    async def _make_api_request(self, url):
        """Make API request with proper error handling."""
        async with aiohttp.ClientSession() as session:
            async with async_timeout.timeout(API_TIMEOUT):
                resp = await session.get(
                    url,
                    headers={"Authorization": self.api_key, "Accept": "application/json"}
                )

                # Obsługa różnych kodów błędu
                if resp.status == 401:
                    _LOGGER.error("API authentication failed - invalid API key")
                    raise UpdateFailed("API authentication failed - invalid API key")
                elif resp.status == 403:
                    _LOGGER.error("API access forbidden - permissions issue")
                    raise UpdateFailed("API access forbidden - check permissions")
                elif resp.status == 404:
                    _LOGGER.error("API endpoint not found - check URL: %s", url)
                    raise UpdateFailed(f"API endpoint not found: {url}")
                elif resp.status == 429:
                    _LOGGER.error("API rate limit exceeded")
                    raise UpdateFailed("API rate limit exceeded - try again later")
                elif resp.status != 200:
                    error_text = await resp.text()
                    _LOGGER.error("API error %s: %s (URL: %s)", resp.status, error_text, url)
                    raise UpdateFailed(f"API error {resp.status}: {error_text[:100]}")

                return await resp.json()


    async def _async_update_data(self):
        """Fetch price and energy data concurrently."""
        _LOGGER.debug("Starting %s price and energy update", self.price_type)

        # --- Prepare Price API Call ---
        today_local_price = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0)
        window_end_local_price = today_local_price + timedelta(days=2)
        start_utc_price = dt_util.as_utc(today_local_price).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_utc_price = dt_util.as_utc(window_end_local_price).strftime("%Y-%m-%dT%H:%M:%SZ")

        price_endpoint_tpl = BUY_ENDPOINT if self.price_type == "buy" else SELL_ENDPOINT
        price_endpoint = price_endpoint_tpl.format(start=start_utc_price, end=end_utc_price)
        price_url = f"{API_URL}{price_endpoint}"
        _LOGGER.debug("Requesting %s price data from %s", self.price_type, price_url)

        # --- Prepare Energy API Call ---
        # Get start and end of *today* in local time for daily energy usage
        today_local_energy = dt_util.now().date() # Use date object for simplicity
        start_local_energy = datetime.combine(today_local_energy, datetime.min.time())
        # API uses end timestamp as exclusive, so we need start of next day
        end_local_energy = datetime.combine(today_local_energy + timedelta(days=1), datetime.min.time())

        # Convert to UTC ISO format strings required by API
        start_utc_energy = dt_util.as_utc(start_local_energy).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_utc_energy = dt_util.as_utc(end_local_energy).strftime("%Y-%m-%dT%H:%M:%SZ")

        energy_endpoint = ENERGY_USAGE_ENDPOINT.format(start=start_utc_energy, end=end_utc_energy)
        energy_url = f"{API_URL}{energy_endpoint}"
        _LOGGER.debug("Requesting energy data from %s", energy_url)

        # --- Execute API Calls Concurrently ---
        results = {}
        try:
            # Use gather to run requests in parallel, return_exceptions=True to handle individual failures
            api_results = await asyncio.gather(
                self.retry_mechanism.execute(self._make_api_request, price_url),
                self.retry_mechanism.execute(self._make_api_request, energy_url),
                return_exceptions=True
            )

            # --- Process Price Data ---
            price_data = api_results[0]
            if isinstance(price_data, Exception):
                _LOGGER.error("Failed to fetch %s price data: %s", self.price_type, price_data)
                # Set price data to None or empty structure if needed by sensors
                results["prices_today"] = []
                results["prices"] = []
                results["current"] = None
                # Optionally re-raise if critical, but gather allows partial success
                # raise UpdateFailed(f"Failed to fetch price data: {price_data}") from price_data
            else:
                frames = price_data.get("frames", [])
                if not frames:
                    _LOGGER.warning("No price frames returned for %s", self.price_type)

                now_utc = dt_util.utcnow()
                prices = []
                current_price = None
                today_local_dt = dt_util.now().replace(hour=0, minute=0, second=0, microsecond=0) # For comparison

                for f in frames:
                    val = convert_price(f.get("price_gross"))
                    if val is None:
                        continue
                    start = dt_util.parse_datetime(f["start"])
                    end = dt_util.parse_datetime(f["end"])

                    if not start or not end:
                        _LOGGER.warning("Invalid datetime format in price frames for %s", self.price_type)
                        continue

                    local_start_str = dt_util.as_local(start).strftime("%Y-%m-%dT%H:%M:%S")
                    prices.append({"start": local_start_str, "price": val})
                    if start <= now_utc < end:
                        current_price = val

                today_str = today_local_dt.strftime("%Y-%m-%d")
                prices_today = [p for p in prices if p["start"].startswith(today_str)]

                _LOGGER.debug("Successfully processed %s price data: current=%s, today_prices=%d",
                             self.price_type, current_price, len(prices_today))
                results["prices_today"] = prices_today
                results["prices"] = prices # Full 48h list
                results["current"] = current_price

            # --- Process Energy Data ---
            energy_data = api_results[1]
            if isinstance(energy_data, Exception):
                _LOGGER.error("Failed to fetch energy data: %s", energy_data)
                results["energy_usage"] = None # Indicate failure
                # Optionally re-raise if critical
                # raise UpdateFailed(f"Failed to fetch energy data: {energy_data}") from energy_data
            else:
                # Assuming API returns structure like: {"total_usage_kwh": 12.34, "usage_frames": [...]}
                # Adjust keys based on actual API response
                total_usage = energy_data.get("total_usage_kwh")
                usage_frames = energy_data.get("usage_frames", []) # Default to empty list

                if total_usage is None:
                     _LOGGER.warning("Energy data received, but 'total_usage_kwh' key is missing or null.")
                     results["energy_usage"] = None # Treat as unavailable if key missing
                else:
                    try:
                        # Validate and store
                        results["energy_usage"] = {
                            "total_usage_kwh": float(total_usage),
                            "usage_frames": usage_frames
                        }
                        _LOGGER.debug("Successfully processed energy data: total_usage=%.2f kWh", float(total_usage))
                    except (ValueError, TypeError):
                        _LOGGER.error("Could not parse energy usage value: %s", total_usage)
                        results["energy_usage"] = None


            # Check if at least one part succeeded
            if isinstance(price_data, Exception) and isinstance(energy_data, Exception):
                 _LOGGER.error("Both price and energy API calls failed.")
                 # Re-raise one of the exceptions to signal complete failure to the coordinator
                 raise UpdateFailed("Both price and energy API calls failed.") from price_data


            return results

        # Catch exceptions not handled by gather's return_exceptions (e.g., timeout before gather)
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout during concurrent API requests for %s", self.price_type)
            raise UpdateFailed(f"API timeout during concurrent requests")
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error during concurrent API requests for %s: %s", self.price_type, str(err))
            raise UpdateFailed(f"Network error: {err}")
        # Catch potential UpdateFailed raised by retry_mechanism or _make_api_request
        except UpdateFailed as err:
             _LOGGER.error("Update failed for %s coordinator: %s", self.price_type, err)
             raise # Re-raise UpdateFailed
        except Exception as err:
            _LOGGER.exception("Unexpected error updating data for %s: %s", self.price_type, str(err))
            raise UpdateFailed(f"Unexpected error: {err}")


    # --- Scheduling methods remain the same ---
    def schedule_hourly_update(self):
        """Schedule next refresh 1 min after each full hour."""
        if self._unsub_hourly:
            self._unsub_hourly()
            self._unsub_hourly = None

        now = dt_util.now()
        # Keep original timing: 1 minute past the hour
        next_run = (now.replace(minute=0, second=0, microsecond=0)
                    + timedelta(hours=1, minutes=1))

        _LOGGER.debug("Scheduling next hourly update for %s at %s",
                     self.name, next_run.isoformat()) # Use self.name

        self._unsub_hourly = async_track_point_in_time(
            self.hass, self._handle_hourly_update, dt_util.as_utc(next_run)
        )


    async def _handle_hourly_update(self, _):
        """Handle hourly update."""
        _LOGGER.debug("Running scheduled hourly update for %s", self.name) # Use self.name
        await self.async_request_refresh()
        self.schedule_hourly_update()


    def schedule_midnight_update(self):
        """Schedule next refresh 1 min after local midnight."""
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None

        now = dt_util.now()
        # Keep original timing: 1 minute past midnight
        next_mid = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)

        _LOGGER.debug("Scheduling next midnight update for %s at %s",
                     self.name, next_mid.isoformat()) # Use self.name

        self._unsub_midnight = async_track_point_in_time(
            self.hass, self._handle_midnight_update, dt_util.as_utc(next_mid)
        )


    async def _handle_midnight_update(self, _):
        """Handle midnight update."""
        _LOGGER.debug("Running scheduled midnight update for %s", self.name) # Use self.name
        await self.async_request_refresh()
        self.schedule_midnight_update()
