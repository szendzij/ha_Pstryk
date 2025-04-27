# Integracja Home Assistant z Pstryk API

[![Wersja](https://img.shields.io/badge/wersja-1.2.1-blue)](https://github.com/twoj_nick/pstryk-homeassistant)

Integracja dla Home Assistant umożliwiająca śledzenie aktualnych cen energii elektrycznej oraz prognoz z platformy PSTryk.

## Funkcje
- 🔌 Aktualna cena kupna i sprzedaży energii
- 📅 Tabela 24h z prognozowanymi cenami
- ⚙️ Konfigurowalna liczba "najlepszych godzin"
- ⏰ Automatyczna konwersja czasu UTC → lokalny
- 🔄 Aktualizacja co 1 minutę po pełnej godzinie
- 🛡️ Obsługa błędów i logowanie diagnostyczne

## Instalacja

### Metoda 1: Via HACS
1. W HACS przejdź do `Integracje`
2. Kliknij `Dodaj repozytorium`
3. Wpisz URL: `https://github.com/twoj_nick/pstryk-homeassistant`
4. Wybierz kategorię: `Integration`
5. Zainstaluj i zrestartuj Home Assistant

### Metoda 2: Ręczna instalacja
1. Utwórz folder `custom_components/pstryk` w katalogu konfiguracyjnym HA
2. Skopiuj pliki:
init.py
manifest.json
config_flow.py
const.py
sensor.py
logo.png (opcjonalnie)
3. Zrestartuj Home Assistant

## Konfiguracja
1. Przejdź do `Ustawienia` → `Urządzenia i usługi`
2. Kliknij `Dodaj integrację`
3. Wyszukaj "Psrryk Energy"
4. Wprowadź dane:
- **Klucz API**: Twój klucz z platformy PSTryk
- **Liczba najlepszych cen kupna**: (domyślnie 5)
- **Liczba najlepszych cen sprzedaży**: (domyślnie 5)

![Przykładowa konfiguracja](https://via.placeholder.com/600x400?text=Konfiguracja+Integracji)

## Użycie
### Dostępne encje
| Nazwa encji                          | Opis                          |
|--------------------------------------|-------------------------------|
| `sensor.pstryk_current_buy_price`    | Aktualna cena kupna           |
| `sensor.pstryk_current_sell_price`   | Aktualna cena sprzedaży       |
| `sensor.pstryk_buy_price_table`      | Tabela cen kupna              |
| `sensor.pstryk_sell_price_table`     | Tabela cen sprzedaży          |

Przykładowa Automatyzacja:

Włączanie bojlera

```yaml
automation:
  - alias: "Optymalne grzanie wody"
    trigger:
      platform: time_pattern
      hours: >
        {{ state_attr('sensor.pstryk_buy_price_table', 'best_prices') 
        | map(attribute='start_local') 
        | map('regex_replace','(..):..','\\1') 
        | list }}
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.bojler
