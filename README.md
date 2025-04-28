# Integracja Home Assistant z Pstryk API

[![Wersja](https://img.shields.io/badge/wersja-1.2.2-blue)](https://github.com/twoj_nick/pstryk-homeassistant)

Integracja dla Home Assistant umożliwiająca śledzenie aktualnych cen energii elektrycznej oraz prognoz z platformy Pstryk.

## Funkcje
- 🔌 Aktualna cena kupna i sprzedaży energii
- 📅 Tabela 24h z prognozowanymi cenami
- ⚙️ Konfigurowalna liczba "najlepszych godzin"
- ⏰ Automatyczna konwersja czasu UTC → lokalny
- 🔄 Aktualizuje dane 1 minutę po pełnej godzinie
- 🛡️ Debug i logowanie

## TODO
- Walidacja kluacza API

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

## Scrnshoty

![{33C89696-2E29-43FF-945F-13B8D14727E4}](https://github.com/user-attachments/assets/231a25fa-c66d-4240-a49a-2ec824985ab2)
![{6613F04E-4045-45A8-A28A-7BA1B8B4AD63}](https://github.com/user-attachments/assets/3edc2ad0-cdd1-46b0-aa58-27ea94bfdd26)
![{C248C3EA-C159-409E-AA40-B9863D7A8311}](https://github.com/user-attachments/assets/48e41d6b-04ae-4f67-b704-7c046646ba11)


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
alias: Optymalne grzanie wody
description: Automatyzacja włączająca grzanie w najtańszych godzinach
trigger:
  - platform: time_pattern
    minutes: "/1"  # Sprawdzaj co minutę

condition:
  - condition: template
    value_template: >
      {% set current_time = now().strftime('%H:%M') %}
      {% set best_hours = state_attr('sensor.pstryk_buy_price_table', 'best_prices') 
        | map(attribute='start') 
        | map('regex_replace', '.* (\d+:\d+):\d+', '\1')  # Wyciągamy samą godzinę (HH:MM)
        | list 
      %}
      {{ current_time in best_hours }}

action:
  - choose:
      - conditions:
          - condition: state
            entity_id: switch.bojler
            state: "off"
        sequence:
          - service: switch.turn_on
            target:
              entity_id: switch.bojler
          - service: notify.mobile_app
            data:
              message: >
                🟢 Grzanie WŁĄCZONE! 
                Godzina: {{ current_time }}, 
                Cena: {{ state_attr('sensor.pstryk_buy_price_table', 'best_prices') 
                  | selectattr('start', 'match', '.* ' + current_time + ':\d+') 
                  | map(attribute='price') 
                  | first | round(2) }} PLN/kWh

      - conditions:
          - condition: state
            entity_id: switch.bojler
            state: "on"
        sequence:
          - delay: "01:05:00"  # Wyłącz po 1 godzinie
          - service: switch.turn_off
            target:
              entity_id: switch.bojler

mode: single
```
Rozładowanie magazynu energii - Sprzedaż po najlepszej cenie

```yaml
