# Integracja Home Assistant z Pstryk API

[![Wersja](https://img.shields.io/badge/wersja-1.2.2-blue)](https://github.com/balgerion/ha_Pstryk/)

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
![IMG_4079](https://github.com/user-attachments/assets/ccdfd05c-3b38-4af5-a8db-36fe7fd645ee)

```yaml
alias: Optymalne grzanie wody
description: ""
triggers:
  - minutes: "1"
    trigger: time_pattern
    hours: /1
conditions:
  - condition: template
    value_template: >
      {% set current_hour = now().replace(minute=0, second=0,
      microsecond=0).isoformat(timespec='seconds').split('+')[0] %}

      {% set best_hours = state_attr('sensor.pstryk_buy_price_table',
      'best_prices') | map(attribute='start') | list %}

      {{ current_hour in best_hours }}
actions:
  - variables:
      current_hour: >-
        {{ now().replace(minute=0, second=0,
        microsecond=0).isoformat(timespec='seconds').split('+')[0] }}
  - choose:
      - conditions:
          - condition: state
            entity_id: light.shellypro3_34987a49142c_switch_2
            state: "off"
        sequence:
          - target:
              entity_id: switch.shellypro3_34987a49142c_switch_2
            action: switch.turn_on
            data: {}
          - data:
              message: |
                Grzanie włączone! Godzina: {{ current_hour }}, Cena: {{
                  state_attr('sensor.pstryk_buy_price_table', 'best_prices')
                  | selectattr('start', 'equalto', current_hour)
                  | map(attribute='price')
                  | first
                }} PLN
            action: notify.mobile_app_balg_iphone
      - conditions:
          - condition: state
            entity_id: light.shellypro3_34987a49142c_switch_2
            state: "on"
        sequence:
          - delay:
              hours: 1
              minutes: 5
          - target:
              entity_id: switch.shellypro3_34987a49142c_switch_2
            action: switch.turn_off
            data: {}

```

Rozładowanie magazynu energii - Sprzedaż po najlepszej cenie

```yaml
