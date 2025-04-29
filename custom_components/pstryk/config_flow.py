"""Config flow for Pstryk Energy integration."""
from homeassistant import config_entries
import voluptuous as vol
from .const import DOMAIN

class PstrykConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pstryk Energy."""
    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
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
    
    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return PstrykOptionsFlowHandler(config_entry)


class PstrykOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Pstryk options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = {
            vol.Required("buy_top", default=self.config_entry.options.get(
                "buy_top", self.config_entry.data.get("buy_top", 5))): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=24)),
            vol.Required("sell_top", default=self.config_entry.options.get(
                "sell_top", self.config_entry.data.get("sell_top", 5))): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=24)),
        }

        return self.async_show_form(
            step_id="init", 
            data_schema=vol.Schema(options)
        )
