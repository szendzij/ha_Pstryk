"""Sensor platform for Pstryk Energy integration."""
import logging
import asyncio
from datetime import datetime, timedelta
# import pytz # Not needed if using dt_util

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass, # Added
)
# Added UnitOfEnergy
from homeassistant.const import UnitOfEnergy, CURRENCY_EURO # Use appropriate currency if needed, or remove
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
# PstrykDataUpdateCoordinator now fetches both price and energy
from .update_coordinator import PstrykDataUpdateCoordinator
from .const import DOMAIN
from homeassistant.helpers.translation import async_get_translations
# Added device info helper
from homeassistant.helpers.device_registry import DeviceInfo


_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up the Pstryk sensors via the coordinator."""
    api_key = hass.data[DOMAIN][entry.entry_id]["api_key"]
    buy_top = entry.options.get("buy_top", entry.data.get("buy_top", 5))
    sell_top = entry.options.get("sell_top", entry.data.get("sell_top", 5))

    _LOGGER.debug("Setting up Pstryk sensors with buy_top=%d, sell_top=%d", buy_top, sell_top)

    # Cleanup old coordinators if they exist (logic remains the same)
    for price_type in ("buy", "sell"):
        key = f"{entry.entry_id}_{price_type}"
        # Use the updated coordinator name convention if changed
        coordinator_key = f"{DOMAIN}_{price_type}_coordinator"
        coordinator = hass.data[DOMAIN].get(coordinator_key) # Check by coordinator name used in super().__init__
        if coordinator:
            _LOGGER.debug("Cleaning up existing %s coordinator", price_type)
            # Cancel scheduled updates
            if hasattr(coordinator, '_unsub_hourly') and coordinator._unsub_hourly:
                coordinator._unsub_hourly()
                coordinator._unsub_hourly = None # Ensure cleanup
            if hasattr(coordinator, '_unsub_midnight') and coordinator._unsub_midnight:
                coordinator._unsub_midnight()
                coordinator._unsub_midnight = None # Ensure cleanup
            # Remove from hass data using the coordinator name key
            hass.data[DOMAIN].pop(coordinator_key, None)

    entities = []
    coordinators_map = {} # Store coordinators to easily access the 'buy' one later

    # Create coordinators first
    for price_type in ("buy", "sell"):
        # Coordinator now fetches both price and energy
        coordinator = PstrykDataUpdateCoordinator(hass, api_key, price_type)
        coordinators_map[price_type] = coordinator
        # Store coordinator under its name for cleanup and potential future use
        hass.data[DOMAIN][coordinator.name] = coordinator


    # Initialize coordinators in parallel to save time
    initial_refresh_tasks = []
    for coordinator in coordinators_map.values(): # Iterate through the created coordinators
        # Check if we're in the setup process or reloading
        try:
            # Newer Home Assistant versions
            from homeassistant.config_entries import ConfigEntryState
            is_setup = entry.state == ConfigEntryState.SETUP_IN_PROGRESS
        except ImportError:
            # Older Home Assistant versions - try another approach
            # Check a flag specific to this entry_id if needed, or rely on coordinator state
            is_setup = not coordinator.last_update_success # Assume first run if no successful update yet

        if is_setup:
            initial_refresh_tasks.append(coordinator.async_config_entry_first_refresh())
        else:
            # Przy przeładowaniu, wymuś odświeżenie, które pobierze oba typy danych
            initial_refresh_tasks.append(coordinator.async_refresh())

    # Wait for all coordinators to finish initial refresh
    refresh_results = await asyncio.gather(*initial_refresh_tasks, return_exceptions=True)

    # Mark as initialized after first setup (can be removed if not strictly needed)
    # hass.data[DOMAIN][f"{entry.entry_id}_initialized"] = True

    # Process coordinators and set up sensors
    energy_sensor_added = False # Flag to add energy sensor only once
    for i, price_type in enumerate(coordinators_map.keys()):
        coordinator = coordinators_map[price_type]

        # Check if initial refresh succeeded for this coordinator
        if isinstance(refresh_results[i], Exception):
            _LOGGER.error("Failed to initialize %s coordinator: %s",
                         price_type, str(refresh_results[i]))
            # Sensors will be created but likely unavailable until coordinator succeeds

        # Schedule updates (already done within coordinator init/methods potentially)
        # Ensure scheduling is called after potential initial failure handling if needed
        # coordinator.schedule_hourly_update() # Scheduling might be better handled within coordinator logic
        # coordinator.schedule_midnight_update()

        # Create Price sensor (existing code)
        top = buy_top if price_type == "buy" else sell_top
        entities.append(PstrykPriceSensor(coordinator, price_type, top, entry)) # Pass entry for device info

        # Create Daily Energy sensor (New) - add only once, associated with 'buy' coordinator
        if price_type == "buy" and not energy_sensor_added:
             entities.append(PstrykDailyEnergySensor(coordinator, entry)) # Pass entry for device info
             energy_sensor_added = True


    async_add_entities(entities, True) # Set update_before_add=True if sensors need data immediately


class PstrykPriceSensor(CoordinatorEntity, SensorEntity):
    """Combined price sensor with table data attributes."""
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True # Use automatic naming

    def __init__(self, coordinator: PstrykDataUpdateCoordinator, price_type: str, top_count: int, entry: ConfigEntry):
        super().__init__(coordinator)
        self.price_type = price_type
        self.top_count = top_count
        self._attr_device_class = SensorDeviceClass.MONETARY # Use SensorDeviceClass
        self._attr_native_unit_of_measurement = "PLN/kWh" # Set directly
        self._translations = {}
        self._entry = entry # Store entry for device info

        # Construct unique_id based on entry_id and price_type
        self._attr_unique_id = f"{entry.entry_id}_{self.price_type}_price"
        # Suggest entity_id (HA might override)
        self.entity_id = f"sensor.pstryk_{self.price_type}_price"


    # ... (async_added_to_hass, _load_translations remain the same) ...
    async def async_added_to_hass(self):
        """When entity is added to Home Assistant."""
        await super().async_added_to_hass()

        # Load translations
        self._translations = await self._load_translations()

    async def _load_translations(self):
        """Load translations for the current language."""
        translations = {}
        try:
            # Ensure DOMAIN is correct and path exists
            translations = await async_get_translations(
                self.hass, self.hass.config.language, "pstryk", ["sensor"] # Adjust components if needed
            )
        except Exception as ex:
            _LOGGER.warning("Failed to load translations for pstryk: %s", ex)
        return translations.get("component.pstryk.entity.sensor", {}) # Navigate to sensor translations


    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        # Use title case for price type
        name_key = f"{self.price_type}_price_name" # e.g., buy_price_name
        # Fallback name if translation not found
        default_name = f"Pstryk Current {self.price_type.title()} Price"
        return self._translations.get(name_key, default_name)


    # unique_id is now set in __init__ using _attr_unique_id

    @property
    def native_value(self):
        """Return the current price."""
        # Access data safely
        if self.coordinator.data and self.coordinator.data.get("current") is not None:
            return self.coordinator.data["current"]
        return None # Return None if data is missing

    # native_unit_of_measurement is set in __init__

    # _get_next_hour_price needs adjustment if translations structure changed
    def _get_next_hour_price(self) -> float | None: # Return type hint
        """Get price data for the next hour."""
        if not self.coordinator.data or not self.coordinator.data.get("prices"):
             _LOGGER.debug("Price data or full price list not available for next hour calculation.")
             return None

        now = dt_util.as_local(dt_util.utcnow())
        next_hour_dt = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        next_hour_iso = next_hour_dt.isoformat(timespec='seconds') # Match format in data if needed

        # Use translations for debug messages if available
        # debug_msg = self._translations.get(
        #     "debug_looking_for_next_hour",
        #     "Looking for price for next hour: {next_hour}"
        # ).format(next_hour=next_hour_iso)
        # _LOGGER.debug(debug_msg)

        # Check prices_today first for efficiency
        prices_today = self.coordinator.data.get("prices_today", [])
        for price_data in prices_today:
             # Assuming price_data["start"] is "YYYY-MM-DDTHH:MM:SS" local time string
             if price_data.get("start", "").startswith(next_hour_dt.strftime("%Y-%m-%dT%H")):
                 _LOGGER.debug("Found next hour price in prices_today: %s", price_data.get('price'))
                 return price_data.get("price")

        # If not found in today's prices (e.g., near midnight), check the full list
        # This part might be redundant if prices_today always covers the relevant next hour
        prices_full = self.coordinator.data.get("prices", [])
        for price_data in prices_full:
             if price_data.get("start", "").startswith(next_hour_dt.strftime("%Y-%m-%dT%H")):
                 _LOGGER.debug("Found next hour price in full prices list: %s", price_data.get('price'))
                 return price_data.get("price")

        _LOGGER.warning("No price found for next hour: %s", next_hour_iso)
        return None


    @property
    def extra_state_attributes(self) -> dict | None:
        """Include the price table attributes."""
        if not self.coordinator.data:
            return None # Return None if no data

        attributes = {}
        now_local = dt_util.now() # Use local time directly

        # Get translated attribute name or use default
        next_hour_key = self._translations.get("next_hour_price", "next_hour_price")
        attributes[next_hour_key] = self._get_next_hour_price()

        prices_today = self.coordinator.data.get("prices_today", [])
        if prices_today: # Avoid sorting empty list
            try:
                # Ensure price is float for sorting, handle potential None
                sorted_prices = sorted(
                    [p for p in prices_today if p.get("price") is not None],
                    key=lambda x: x["price"],
                    reverse=(self.price_type == "sell"),
                )
                attributes["best_prices"] = sorted_prices[: self.top_count]
            except Exception as e:
                 _LOGGER.error("Error sorting prices: %s", e)
                 attributes["best_prices"] = [] # Provide empty list on error
        else:
            attributes["best_prices"] = []


        attributes["all_prices_today"] = prices_today # Use a distinct key
        attributes["top_count"] = self.top_count
        attributes["price_count_today"] = len(prices_today)
        # Use coordinator's last update time if available
        if self.coordinator.last_update_success_time:
             attributes["last_update"] = self.coordinator.last_update_success_time.isoformat()
        else:
             attributes["last_update"] = now_local.isoformat() # Fallback

        return attributes

    @property
    def available(self) -> bool:
        """Return if entity is available based on price data."""
        # Check coordinator success AND presence of price-specific data
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None and
            self.coordinator.data.get("current") is not None # Check if current price exists
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link entities."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"Pstryk Energy ({self._entry.title})", # Use entry title or a fixed name
            manufacturer="Pstryk.pl", # Or appropriate manufacturer
            model="API Integration",
            entry_type="service", # Or appropriate type
        )


# --- New class for Daily Energy Sensor ---
class PstrykDailyEnergySensor(CoordinatorEntity, SensorEntity):
    """Sensor for daily energy usage from Pstryk API."""
    _attr_state_class = SensorStateClass.TOTAL_INCREASING # More accurate for daily total
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_has_entity_name = True # Use automatic naming based on class name

    # Optional: Define a suggested icon
    # _attr_icon = "mdi:lightning-bolt"

    def __init__(self, coordinator: PstrykDataUpdateCoordinator, entry: ConfigEntry):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry # Store entry for device info and unique ID

        # Unique ID based on the config entry ID ensures it's unique per integration instance
        self._attr_unique_id = f"{entry.entry_id}_daily_energy"
        # Suggest entity_id (HA might override)
        self.entity_id = f"sensor.pstryk_daily_energy_usage"

        # Load translations if needed for name/attributes
        self._translations = {} # Placeholder for potential future translations


    # Add async_added_to_hass if translations are needed for this sensor specifically
    # async def async_added_to_hass(self):
    #    await super().async_added_to_hass()
    #    # Load specific translations if necessary

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        # Could use translations here if defined
        return "Pstryk Daily Energy Usage" # Default name

    @property
    def native_value(self):
        """Return the state of the sensor (total daily usage)."""
        if (
            self.coordinator.data and
            # Safely access nested dictionary
            (energy_data := self.coordinator.data.get("energy_usage")) and
            # Check if the specific key exists and is not None
            (total_usage := energy_data.get("total_usage_kwh")) is not None
        ):
            try:
                # Value should already be float from coordinator processing
                return total_usage
            except (ValueError, TypeError):
                # Log error if conversion failed earlier, but return None here
                 _LOGGER.warning("Stored energy usage value is not a valid number: %s", total_usage)
                 return None
        # Return None if energy_usage data or total_usage_kwh is missing/None
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the state attributes."""
        attributes = {}
        if (
            self.coordinator.data and
            (energy_data := self.coordinator.data.get("energy_usage"))
        ):
            # Add usage frames if they exist in the data
            attributes["usage_frames"] = energy_data.get("usage_frames", [])

            # Add last update time from coordinator
            if self.coordinator.last_update_success_time:
                 attributes["last_api_update"] = self.coordinator.last_update_success_time.isoformat()

        return attributes if attributes else None # Return None if no attributes

    @property
    def available(self) -> bool:
        """Return if entity is available based on energy data."""
        # Check coordinator success AND presence of energy-specific data
        return (
            self.coordinator.last_update_success and
            self.coordinator.data is not None and
            (energy_data := self.coordinator.data.get("energy_usage")) is not None and
            energy_data.get("total_usage_kwh") is not None # Crucial check
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link entities."""
        # Use the same device info as the price sensors
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            # Name, manufacturer etc. inherited from the price sensor's device info definition
            # Or define them explicitly again here if needed
            name=f"Pstryk Energy ({self._entry.title})",
            manufacturer="Pstryk.pl",
            model="API Integration",
            entry_type="service",
        )
