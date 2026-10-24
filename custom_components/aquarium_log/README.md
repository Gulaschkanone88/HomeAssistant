# Aquarium-Tagebuch

Eigene Home-Assistant-Integration, mit der sich Wasserwerte aus dem Testkoffer und
Pflegeereignisse wie Wasserwechsel mit Datum und Uhrzeit erfassen lassen. Auch
ältere Werte, etwa aus einem Notizbuch, können mit ihrem ursprünglichen Zeitpunkt
nachgetragen werden und erscheinen dann an der richtigen Stelle im Verlauf.

Getestet mit Home Assistant 2026.2.3. Ältere Versionen wurden nicht geprüft; die
Statistik-Schnittstelle in der verwendeten Form gibt es erst seit 2025.11.

## Was die Integration anlegt

| Bestandteil | Zweck |
|---|---|
| Dashboard-Karte `custom:aquarium-log-card` | Eingabe (Wassertest oder Ereignis), Verlauf je Wert mit Sollbereich und eingezeichneten Ereignissen, Tagebuch mit Bearbeiten und Löschen, Grenzwerte und Meldungen einstellen |
| Sensor je Wasserwert, z. B. `sensor.aquarium_ph_wert` | Jüngster Messwert nach Messzeitpunkt, Attribute `measured_at`, `min`, `max`, `out_of_range` |
| `binary_sensor.aquarium_grenzwertwarnung` | An, solange ein Wert mehrfach in Folge außerhalb seiner Grenzen liegt; Details im Attribut `violations` |
| `sensor.aquarium_letzter_wasserwechsel` | Zeitpunkt des letzten Wasserwechsels mit Menge und Anteil |
| `calendar.aquarium_tagebuch` | Alle Messungen und Ereignisse als Kalendereinträge |
| Langzeitstatistik `aquarium_log:<becken>_<wert>` | Vollständiger Verlauf inklusive nachgetragener Werte für die Statistik-Diagramm-Karte und den Statistik-Bereich der Entwicklerwerkzeuge |

Die Rohdaten liegen in `config/.storage/aquarium_log.<entry_id>` und sind damit
Teil jedes normalen Home-Assistant-Backups.

Vorausgewählt sind die Tests der sera aqua-test box (+Cl): pH, KH, GH, Nitrit,
Nitrat und Chlor. Ammonium, Phosphat, Eisen, Kupfer, CO₂, Sauerstoff, Temperatur und
Leitwert lassen sich jederzeit über *Konfigurieren* zuschalten. Bereits gespeicherte
Messungen gehen beim Abwählen nicht verloren.

## Grenzwerte und Meldungen

Im Reiter *Grenzen* der Karte stehen Minimum und Maximum je Wasserwert. Ein leeres Feld
bedeutet keine Grenze. Im Verlauf erscheint der Sollbereich als grünes Band mit
gestrichelten Grenzlinien, Messpunkte außerhalb sind rot. Beim Erfassen zeigt jedes Feld
seinen Sollbereich und färbt sich rot, sobald der eingetippte Wert außerhalb liegt.

Vorbelegt sind Richtwerte für ein Süßwasser-Gesellschaftsbecken. Sie sind ein
Ausgangspunkt, keine Empfehlung für einen bestimmten Besatz:

| Wert | Start-Grenzen | Herkunft |
|---|---|---|
| pH | 6,5–7,5 | Händler-/Herstellertabelle „Süßwasser mit Fischen“ |
| KH | 5–10 °dH | sera, Gesellschaftsaquarium |
| GH | 5–15 °dH | sera |
| Nitrit | max. 0,5 mg/l | sera (ideal: nicht nachweisbar) |
| Nitrat | max. 50 mg/l | sera |
| Chlor | max. 0 mg/l | sera Cl-Test: jede nachweisbare Menge ist schädlich |

Eine Meldung entsteht, wenn die jüngsten Messungen eines Werts mehrfach in Folge außerhalb
der Grenzen liegen (Standard 2, einstellbar). Gemeldet wird einmal beim Überschreiten:

| Kanal | Verhalten |
|---|---|
| Benachrichtigung in Home Assistant | Erscheint unter der Glocke und verschwindet von selbst, sobald eine Messung wieder im Bereich liegt (abschaltbar) |
| Push aufs Handy | An alle in der Karte angehakten `notify.*`-Dienste, z. B. `notify.mobile_app_<handy>` der Companion App |
| Ereignisse | `aquarium_log_limit_exceeded` und `aquarium_log_limit_cleared` für eigene Automationen |
| Binärsensor | `binary_sensor.aquarium_grenzwertwarnung` |

Einstellen geht auch per Dienst:

```yaml
action: aquarium_log.configure
data:
  limits:
    no3:
      min: null
      max: 25
  alert_count: 2
  notify_services:
    - notify.mobile_app_mein_handy
```

## Schnittstelle für Auswertungen

Für Analysen gibt es zwei lesende Schnittstellen. Beide rechnen mit derselben Logik
(`analysis.py`) und liefern JSON.

### KI-Assistenten über MCP

Die Integration meldet in Home Assistant eine eigene LLM-API „Aquarium-Tagebuch“ an. Der
in Home Assistant eingebaute MCP-Server gibt sie an MCP-fähige Assistenten wie Claude
weiter. Verfügbare Werkzeuge:

| Werkzeug | Liefert |
|---|---|
| `aquarium_summary` | Je Wert: letzter Stand, Grenzen, Status, Mittel/Min/Max, Trend pro Woche, Anteil außerhalb der Grenzen; Wasserwechsel-Statistik; aktive Warnungen |
| `aquarium_measurements` | Rohdaten der Wassertests, filterbar nach Wert und Zeitraum |
| `aquarium_events` | Pflegeereignisse, filterbar nach Art und Zeitraum |
| `aquarium_analyze` | Ein Wert im Detail: Wirkung jedes Wasserwechsels (vorher/nachher), Veränderung pro Tag zwischen den Wechseln, Prognose bis zur Grenze, Messreihe |

Einrichtung:

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Model Context Protocol Server*
   und als API „Aquarium-Tagebuch“ auswählen (zusätzlich „Assist“, wenn der Assistent auch
   Geräte steuern soll).
2. Im Benutzerprofil unter *Sicherheit* ein langlebiges Zugriffstoken erstellen.
3. Den Assistenten auf `https://<deine-ha-adresse>/api/mcp` zeigen lassen, z. B. in Claude Code:

   ```bash
   claude mcp add --transport http aquarium https://<deine-ha-adresse>/api/mcp \
     --header "Authorization: Bearer <token>"
   ```

Danach lassen sich Fragen stellen wie „Wie schnell steigt mein Nitrat zwischen den
Wasserwechseln?“ oder „Reicht mein Wechselintervall, um unter 50 mg/l zu bleiben?“.

Der Assistent muss Home Assistant über das Netz erreichen. Läuft er auf einem Rechner im
Heimnetz, genügt die lokale Adresse; ein Assistent in der Cloud braucht eine öffentlich
erreichbare Adresse, z. B. über Nabu Casa.

### REST-API

Alle Aufrufe brauchen den Header `Authorization: Bearer <token>`. Bei mehreren Becken
wählt `aquarium=<Name>` das Becken.

| Aufruf | Inhalt |
|---|---|
| `GET /api/aquarium_log/summary?days=90` | Überblick wie `aquarium_summary`, `days=0` = alles |
| `GET /api/aquarium_log/measurements?start=2026-01-01&end=2026-06-30&parameter=no3` | Messungen; `format=csv` liefert CSV |
| `GET /api/aquarium_log/events?event_type=water_change` | Ereignisse |
| `GET /api/aquarium_log/analysis/no3?days=180` | Auswertung wie `aquarium_analyze` |

Beispiel:

```bash
curl -H "Authorization: Bearer $HA_TOKEN" \
  "https://<deine-ha-adresse>/api/aquarium_log/measurements?format=csv" > aquarium.csv
```

Für die Auswertung der Wasserwechsel zählt die letzte Messung bis 7 Tage vor und die erste
Messung bis 3 Tage nach dem Wechsel. Die Prognose rechnet linear mit der mittleren
Veränderung zwischen den Wechseln; bei wenigen Messpunkten ist sie entsprechend grob.

## Installation

1. Den Ordner `custom_components/aquarium_log` nach `config/custom_components/aquarium_log`
   kopieren (Samba, File Editor, Studio Code Server oder SSH).
2. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Aquarium-Tagebuch*,
   Namen des Beckens eingeben und die Wasserwerte des eigenen Testkoffers auswählen.
4. Auf einem Dashboard die Karte hinzufügen (siehe unten). Die Karte wird von der
   Integration selbst geladen, eine Dashboard-Ressource ist nicht nötig. Nach einem
   Update der Integration ggf. den Browser-Cache bzw. die App neu laden.

## Dashboard

Minimal reicht:

```yaml
type: custom:aquarium-log-card
```

Optionen der Karte:

| Option | Standard | Bedeutung |
|---|---|---|
| `title` | Name des Beckens | Überschrift |
| `days` | `90` | Voreingestellter Zeitraum im Verlauf (`0` = alles) |
| `default_tab` | `add` | Starttab: `add`, `chart`, `journal` oder `limits` |
| `entry_id` | – | Nur nötig, wenn mehrere Becken eingerichtet sind |

Ein vollständiges Beispiel mit Karte, Statistik-Diagramm und Kalender steht in
[`dashboard_beispiel.yaml`](dashboard_beispiel.yaml).

Wichtig für eigene Diagramme: Die normalen Verlaufsdiagramme (History) kennen nur den
Zeitpunkt, zu dem ein Sensor seinen Zustand geändert hat. Nachgetragene Werte fehlen
dort. Für einen sauberen Verlauf deshalb die Statistik-Diagramm-Karte mit den
`aquarium_log:`-Statistiken verwenden oder die Karte dieser Integration.

## Dienste

Alle Eingaben laufen über Dienste und lassen sich damit auch aus Automationen,
Skripten oder per REST-API nutzen.

| Dienst | Zweck |
|---|---|
| `aquarium_log.add_measurement` | Messung speichern, `timestamp` optional (leer = jetzt) |
| `aquarium_log.add_event` | Ereignis speichern: `water_change`, `fertilizer`, `conditioner`, `filter`, `cleaning`, `plants`, `livestock`, `medication`, `technology`, `other` |
| `aquarium_log.update_item` | Eintrag ändern |
| `aquarium_log.delete_item` | Eintrag löschen |
| `aquarium_log.configure` | Grenzwerte, Anzahl Messungen bis zur Meldung, Meldekanäle |
| `aquarium_log.export` | Alle Einträge als Liste und CSV (Semikolon-getrennt) zurückgeben |

Beispiel, alte Notizbuchwerte nachtragen:

```yaml
action: aquarium_log.add_measurement
data:
  timestamp: "2026-03-14 19:30:00"
  ph: 7.2
  kh: 6
  gh: 10
  no2: 0
  no3: 25
  note: aus dem Notizbuch
```

Beispiel, Wasserwechsel:

```yaml
action: aquarium_log.add_event
data:
  event_type: water_change
  volume_liters: 60
  percent: 30
```

Beispiel, Erinnerung nach 7 Tagen ohne Wasserwechsel:

```yaml
triggers:
  - trigger: template
    value_template: >
      {{ states('sensor.aquarium_letzter_wasserwechsel') not in ['unknown', 'unavailable']
         and now() - as_datetime(states('sensor.aquarium_letzter_wasserwechsel')) > timedelta(days=7) }}
actions:
  - action: notify.notify
    data:
      message: "Letzter Wasserwechsel liegt mehr als 7 Tage zurück."
```

## Grenzen

Die Statistik speichert stündliche Mittelwerte. Zwei Messungen desselben Werts in
derselben Stunde werden dort gemittelt; im Tagebuch und in der Karte bleiben beide
einzeln sichtbar.

Bewertet wird immer die Reihenfolge nach Messzeitpunkt. Ein nachgetragener alter Wert
löst deshalb nur dann eine Meldung aus, wenn er zu den jüngsten Messungen gehört.
