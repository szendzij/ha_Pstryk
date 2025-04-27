from homeassistant import config_entries
import voluptuous as vol
from .const import DOMAIN

class PstrykConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(
                title="Pstryk Energy", 
                data=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("api_key"): str,
                vol.Required("buy_top", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=24)),
                vol.Required("sell_top", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=24))
            }),
            errors=errors
        )
