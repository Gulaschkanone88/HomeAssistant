# Wärmepumpen-Blueprints

Zwei Template-Blueprints für Home Assistant, die aus Wärmeleistung und
Stromaufnahme die Leistungszahl einer Wärmepumpe berechnen.

| Blueprint | Erzeugt | Eingaben |
|---|---|---|
| `waermepumpe_cop.yaml` | Momentaner COP | Wärmeleistung, elektrische Leistung, drei Gültigkeitsgrenzen, optionale Sperrentitäten |
| `waermepumpe_arbeitszahl.yaml` | Arbeitszahl über einen Zeitraum | Wärmemengenzähler, Stromzähler, Mindestmenge, Plausibilitätsgrenze |

## Formeln

Momentanwert, beide Größen intern in Watt:

```
COP = Wärmeleistung / elektrische Leistung
```

Über einen Zeitraum, beide Größen intern in Kilowattstunden:

```
Arbeitszahl = Wärmemenge / Stromverbrauch
```

Liefert die Anlage keine Wärmeleistung, lässt sie sich aus Volumenstrom und
Spreizung bilden:

```
P_th [kW] = Volumenstrom [l/h] × Spreizung [K] × 1,163 [Wh/(l·K)] / 1000
```

Die Konstante 1,163 gilt für reines Wasser. Bei Glykolanteil im Kreis liegt
die spezifische Wärmekapazität niedriger und damit auch die tatsächliche
Wärmeleistung.

## Installation

Die beiden Blueprints `waermepumpe_cop.yaml` und `waermepumpe_arbeitszahl.yaml`
nach `config/blueprints/template/` legen und in der `configuration.yaml` per
`use_blueprint` einbinden – ein Beispiel steht in
`waermepumpe_beispiel_configuration.yaml`. Diese Beispieldatei ist kein
Blueprint und gehört nicht mit in den Blueprint-Ordner. Eine Oberfläche zum
Anlegen gibt es für Template-Blueprints nicht, die Einbindung läuft über YAML.

Die Namen in der Beispielkonfiguration sind bewusst ohne Umlaute geschrieben.
Home Assistant bildet die Entity-ID aus dem Namen und macht dabei aus „ä“ ein
„a“, aus „WP Wärmemenge“ würde also `sensor.wp_warmemenge`. Die Verweise
zwischen den Sensoren passen dann nicht mehr.

Jeder Blueprint erzeugt genau eine Entität. Mehrere Entitäten entstehen,
indem derselbe Blueprint mehrfach eingebunden wird – für Tages-, Monats- und
Jahresarbeitszahl also dreimal.

## Einheiten

Beide Blueprints lesen die Einheit aus dem Attribut `unit_of_measurement` der
angegebenen Sensoren und rechnen intern um. Für Leistung werden W, kW und MW
erkannt, für Energie Wh, kWh und MWh. Die beiden Quellen dürfen sich also in
der Einheit unterscheiden.

## Gültigkeitsgrenzen

Statt bei ungültigen Bedingungen eine 0 auszugeben, setzen beide Blueprints
den Sensor auf `unavailable`. Eine 0 während Standby oder Abtauung würde jeden
Tages- und Monatsmittelwert nach unten ziehen; `unavailable` wird von den
Statistiken übergangen.

Der Momentan-COP rechnet nur, wenn die elektrische Leistung und die
Wärmeleistung jeweils über ihrer Untergrenze liegen und das Ergebnis unter der
oberen Plausibilitätsgrenze bleibt. Die Untergrenzen fangen den Standby-Betrieb
und die Abtauung ab, die Obergrenze das Messrauschen des trägen
Durchflusssensors beim Anlagenstart.

## Elektrischer Zusatzheizer

Der häufigste Fehler bei dieser Rechnung: Der Stromzähler erfasst den
Heizstab nicht, dessen Wärme steckt aber im Wärmeleistungssensor, weil der
hinter dem Zusatzheizer misst. Der COP fällt dann in genau den Phasen zu gut
aus, in denen die Anlage am ineffizientesten arbeitet.

Für den Momentanwert gibt es dafür die Eingabe **Sperrende Entitäten** – ist
eine davon `on`, liefert der Sensor nichts. Für die Arbeitszahl gehört die
elektrische Energie des Heizstabs in den Stromzähler; ein Heizstab arbeitet
mit einem Wirkungsgrad nahe 1, seine thermischen und elektrischen
Kilowattstunden sind also praktisch identisch.

## Genauigkeit

Der Durchflusssensor ist der größte Unsicherheitsfaktor. Bei Anlagenstart und
beim Abtauen hinkt er dem tatsächlichen Volumenstrom hinterher; Momentanwerte
aus diesen Phasen sind unbrauchbar. Ein geeichter Wärmemengenzähler ist die
einzige Möglichkeit, die absolute Größe zu belegen. Für Trends und den
Vergleich von Betriebseinstellungen reicht diese Rechnung.

## Getestet

Home Assistant 2026.9.1, Daikin-Rotex-HPSU über die CAN-Anbindung, Stromzähler
über Z-Wave. Die Templates wurden am 29.09.2026 gegen die laufende Instanz
gerendert: 4,17 kW thermisch bei 1510 W elektrisch während der
Warmwasserbereitung ergaben einen COP von 2,76.
