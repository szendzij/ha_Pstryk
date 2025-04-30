"""Sensor platform for Pstryk Energy integration."""
import logging
import asyncio
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from .update_coordinator import PstrykDataUpdateCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up the four Pstryk sensors via the coordinator."""
    api_key = hass.data[DOMAIN][entry.entry_id]["api_key"]
    buy_top = entry.options.get("buy_top", entry.data.get("buy_top", 5))
    sell_top = entry.options.get("sell_top", entry.data.get("sell_top", 5))

    _LOGGER.debug("Setting up Pstryk sensors with buy_top=%d, sell_top=%d", buy_top, sell_top)

    # Cleanup old coordinators if they exist
    for price_type in ("buy", "sell"):
        key = f"{entry.entry_id}_{price_type}"
        coordinator = hass.data[DOMAIN].get(key)
        if coordinator:
            _LOGGER.debug("Cleaning up existing %s coordinator", price_type)
            # Cancel scheduled updates
            if hasattr(coordinator, '_unsub_hourly') and coordinator._unsub_hourly:
                coordinator._unsub_hourly()
            if hasattr(coordinator, '_unsub_midnight') and coordinator._unsub_midnight:
                coordinator._unsub_midnight()
            # Remove from hass data
            hass.data[DOMAIN].pop(key, None)

    entities = []
    coordinators = []
    
    # Create coordinators first
    for price_type in ("buy", "sell"):
        key = f"{entry.entry_id}_{price_type}"
        coordinator = PstrykDataUpdateCoordinator(hass, api_key, price_type)
        coordinators.append((coordinator, price_type, key))
        
    # Initialize coordinators in parallel to save time
    initial_refresh_tasks = []
    for coordinator, _, _ in coordinators:
        # Check if we're in the setup process or reloading
        try:
            # Newer Home Assistant versions
            from homeassistant.config_entries import ConfigEntryState
            is_setup = entry.state == ConfigEntryState.SETUP_IN_PROGRESS
        except ImportError:
            # Older Home Assistant versions - try another approach
            is_setup = not hass.data[DOMAIN].get(f"{entry.entry_id}_initialized", False)
            
        if is_setup:
            initial_refresh_tasks.append(coordinator.async_config_entry_first_refresh())
        else:
            initial_refresh_tasks.append(coordinator.async_refresh())
            
    refresh_results = await asyncio.gather(*initial_refresh_tasks, return_exceptions=True)
    
    # Mark as initialized after first setup
    hass.data[DOMAIN][f"{entry.entry_id}_initialized"] = True
    
    # Process coordinators and set up sensors
    for i, (coordinator, price_type, key) in enumerate(coordinators):
        # Check if initial refresh succeeded
        if isinstance(refresh_results[i], Exception):
            _LOGGER.error("Failed to initialize %s coordinator: %s", 
                         price_type, str(refresh_results[i]))
            # Still add coordinator and set up sensors even if initial load failed
        
        # Schedule updates
        coordinator.schedule_hourly_update()
        coordinator.schedule_midnight_update()
        hass.data[DOMAIN][key] = coordinator

        entities.append(PstrykCurrentPriceSensor(coordinator, price_type))
        top = buy_top if price_type == "buy" else sell_top
        entities.append(PstrykPriceTableSensor(coordinator, price_type, top))

    async_add_entities(entities, True)


class PstrykCurrentPriceSensor(CoordinatorEntity, SensorEntity):
    """Current price sensor."""
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PstrykDataUpdateCoordinator, price_type: str):
        super().__init__(coordinator)
        self.price_type = price_type
        self._attr_device_class = "monetary"

    @property
    def name(self) -> str:
        return f"Pstryk Current {self.price_type.title()} Price"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_{self.price_type}_current"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("current")

    @property
    def native_unit_of_measurement(self) -> str:
        return "PLN/kWh"
        
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None


class PstrykPriceTableSensor(CoordinatorEntity, SensorEntity):
    """Today's price table sensor."""
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PstrykDataUpdateCoordinator, price_type: str, top_count: int):
        super().__init__(coordinator)
        self.price_type = price_type
        self.top_count = top_count

    @property
    def name(self) -> str:
        return f"Pstryk {self.price_type.title()} Price Table"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_{self.price_type}_table"

    @property
    def native_value(self) -> int:
        # number of price slots today
        if self.coordinator.data is None:
            return 0
        return len(self.coordinator.data.get("prices_today", []))

    @property
    def extra_state_attributes(self) -> dict:
        if self.coordinator.data is None:
            return {
                "all_prices": [],
                "best_prices": [],
                "top_count": self.top_count,
                "last_updated": dt_util.as_local(dt_util.utcnow()).isoformat(),
                "data_available": False
            }
            
        today = self.coordinator.data.get("prices_today", [])
        sorted_prices = sorted(
            today,
            key=lambda x: x["price"],
            reverse=(self.price_type == "sell"),
        )
        return {
            "all_prices": today,
            "best_prices": sorted_prices[: self.top_count],
            "top_count": self.top_count,
            "last_updated": dt_util.as_local(dt_util.utcnow()).isoformat(),
            "data_available": True
        }
        
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None
