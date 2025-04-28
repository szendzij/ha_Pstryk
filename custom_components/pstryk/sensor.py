import logging
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

    entities = []
    for price_type in ("buy", "sell"):
        key = f"{entry.entry_id}_{price_type}"
        coordinator: PstrykDataUpdateCoordinator = hass.data[DOMAIN].get(key)
        if not coordinator:
            coordinator = PstrykDataUpdateCoordinator(hass, api_key, price_type)
            await coordinator.async_config_entry_first_refresh()
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

    @property
    def name(self) -> str:
        return f"Pstryk Current {self.price_type.title()} Price"

    @property
    def unique_id(self) -> str:
        return f"{DOMAIN}_{self.price_type}_current"

    @property
    def native_value(self):
        return self.coordinator.data.get("current")

    @property
    def native_unit_of_measurement(self) -> str:
        return "PLN/kWh"


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
        return len(self.coordinator.data.get("prices_today", []))

    @property
    def extra_state_attributes(self) -> dict:
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
        }
