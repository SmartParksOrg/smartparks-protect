"""The Dutch of the server's fixed texts (decision D240). Keys are the English texts, or
templates with `{placeholders}` where the English is composed with names and figures. The
words follow the interface catalogue (`services/frontend/src/locales/nl`): apparaat, entiteit,
fix, gebeurtenis, alarm, kaartobject. `tests/shared/test_i18n.py` checks that every fixed
text the code composes has its entry."""

# ruff: noqa: E501

NL: dict[str, str] = {
    # the reasons of a move or a bulk action (shared/domain/moves.py, decisions D292 to D294)
    "already in this project": "zit al in dit project",
    "not found": "niet gevonden",
    "not in a project; assign it instead": "zit in geen project; wijs het toe in plaats van te verplaatsen",
    "not in a project at that moment; assign it instead": "zat op dat moment in geen project; wijs het toe in plaats van te verplaatsen",
    "another device, {device}, tracked it": "een ander apparaat, {device}, volgde het",
    "{device} is not moving": "{device} verhuist niet mee",
    "{device} tracked it before {moment} UTC": "{device} volgde het al vóór {moment} UTC",
    "the target project has an entity of that name": "het doelproject heeft al een entiteit met die naam",
    "the entity {name} cannot move: the target project has an entity of that name": "de entiteit {name} kan niet mee: het doelproject heeft al een entiteit met die naam",
    "already in the target project": "zit al in het doelproject",
    "not found in this project": "niet gevonden in dit project",
    "device not found": "apparaat niet gevonden",
    "an entity of that name exists": "er bestaat al een entiteit met die naam",
    "not in this project at the start": "zat bij het begin niet in dit project",
    "tracks an entity from the start on; release it first": "volgt vanaf het begin al een entiteit; maak het eerst los",
    # the explanations (shared/domain/explanations.py)
    "The device's status message carries one or more error flags. Each flag is explained below; a flag that clears on the next status was a passing fault.": "Het statusbericht van het apparaat bevat een of meer foutvlaggen. Elke vlag wordt hieronder uitgelegd; een vlag die bij de volgende status weer weg is, was een voorbijgaande storing.",
    "The device started again: its uptime dropped back to zero. A single restart is harmless; repeated restarts point at a firmware or a power problem.": "Het apparaat is opnieuw gestart: zijn uptime viel terug naar nul. Eén herstart is onschuldig; herhaalde herstarts wijzen op een firmware- of voedingsprobleem.",
    "The external switch on the device became active.": "De externe schakelaar op het apparaat werd actief.",
    "The external switch on the device became inactive.": "De externe schakelaar op het apparaat werd inactief.",
    "The fence monitor could not measure the fence voltage. Check the fence connection.": "De hekbewaking kon de hekspanning niet meten. Controleer de aansluiting van het hek.",
    "Nothing has been received from this entity for the time the rule sets. The device may be out of network range, out of battery, or stored records are waiting for a connection; the delivery from the network may also have stopped.": "Van deze entiteit is niets ontvangen gedurende de tijd die de regel stelt. Het apparaat kan buiten netwerkbereik zijn, een lege batterij hebben, of opgeslagen records wachten op een verbinding; ook de aflevering door het netwerk kan zijn gestopt.",
    "The battery voltage fell below the rule's threshold. Plan a battery change or check the charging before the device stops sending.": "De batterijspanning zakte onder de drempel van de regel. Plan een batterijwissel of controleer het laden voordat het apparaat stopt met zenden.",
    "The device's accelerometer has not changed between status messages for the time the rule sets. The device may have dropped off, or the animal is not moving; check the last position and the movement line on the entity page.": "De versnellingsmeter van het apparaat is tussen statusberichten niet veranderd gedurende de tijd die de regel stelt. Het apparaat kan zijn afgevallen, of het dier beweegt niet; controleer de laatste positie en de bewegingsregel op de entiteitpagina.",
    "The entity's position left the geofence named in the title.": "De positie van de entiteit heeft de geofence uit de titel verlaten.",
    "The entity's position entered the geofence named in the title.": "De positie van de entiteit is de geofence uit de titel binnengegaan.",
    "The entity came within the distance the rule sets of the place or entity named.": "De entiteit kwam binnen de afstand die de regel stelt van de genoemde plaats of entiteit.",
    "The speed the device reported with its fix was above the rule's limit: the receiver's speed over ground at that moment, not an average between two fixes. A device that reports no speed never raises this.": "De snelheid die het apparaat bij zijn fix meldde lag boven de limiet van de regel: de grondsnelheid van de ontvanger op dat moment, geen gemiddelde tussen twee fixes. Een apparaat dat geen snelheid meldt, geeft dit nooit.",
    "A background worker of the server has not reported for longer than allowed; the work it does (decoding, rules, exports, analyses) waits until it is back.": "Een achtergrondworker van de server heeft zich langer dan toegestaan niet gemeld; het werk dat hij doet (decoderen, regels, exports, analyses) wacht tot hij terug is.",
    "Messages on the server's bus failed repeatedly and were set aside. Nothing is lost, but a server admin should look at them under System health.": "Berichten op de bus van de server zijn herhaaldelijk mislukt en apart gezet. Er is niets verloren, maar een serverbeheerder moet ernaar kijken onder Systeemgezondheid.",
    "The server's workers are behind on their queues; data arrives later than usual until they catch up.": "De workers van de server lopen achter op hun wachtrijen; data komt later aan dan gewoonlijk tot ze zijn bijgewerkt.",
    "The last backup or restore test did not succeed; a server admin should check it.": "De laatste back-up of hersteltest is niet gelukt; een serverbeheerder moet dit controleren.",
    "The reason the device gives: ": "De reden die het apparaat geeft: ",
    "{flag}: no explanation yet.": "{flag}: nog geen uitleg.",
    # the error flags
    "The LoRa radio module (LR11xx) reported an error, so the device could not use its radio as it should. One occurrence usually clears by itself; a flag that stays on points at the radio hardware or its firmware.": "De LoRa-radiomodule (LR11xx) meldde een fout, zodat het apparaat zijn radio niet kon gebruiken zoals het hoort. Eén keer verdwijnt meestal vanzelf; een vlag die aan blijft, wijst op de radiohardware of zijn firmware.",
    "The Bluetooth module reported an error. Positions and status are not affected.": "De Bluetooth-module meldde een fout. Posities en status zijn niet geraakt.",
    "The GPS receiver (u-blox) did not answer as expected. The device keeps sending its status, but positions can be missing until the receiver recovers.": "De GPS-ontvanger (u-blox) antwoordde niet zoals verwacht. Het apparaat blijft zijn status sturen, maar posities kunnen ontbreken tot de ontvanger herstelt.",
    "The accelerometer did not answer, so movement cannot be measured until it recovers.": "De versnellingsmeter antwoordde niet, dus beweging kan niet worden gemeten tot hij herstelt.",
    "The battery is below the firmware's critical level. The device may reduce its work or stop sending; plan a battery change or check the charging.": "De batterij zit onder het kritieke niveau van de firmware. Het apparaat kan zijn werk beperken of stoppen met zenden; plan een batterijwissel of controleer het laden.",
    "The GPS did not get a fix within the time allowed, so that attempt gave no position. Common under dense canopy, indoors, or when the device lies with its antenna down; when it persists, the sky view or the antenna is the problem.": "De GPS kreeg binnen de toegestane tijd geen fix, dus die poging gaf geen positie. Komt vaak voor onder dicht bladerdak, binnen, of als het apparaat met de antenne omlaag ligt; houdt het aan, dan is het zicht op de hemel of de antenne het probleem.",
    "The flash memory reported an error. Records stored on the device may be delayed or lost until it recovers.": "Het flashgeheugen meldde een fout. Records die op het apparaat zijn opgeslagen, kunnen vertraagd of verloren raken tot het herstelt.",
    "The GPS receiver was still busy with the previous attempt.": "De GPS-ontvanger was nog bezig met de vorige poging.",
    "The device could not join the LoRaWAN network: no gateway answered its join request. It keeps trying and stores its records meanwhile; they arrive once it joins. Check the gateways near the device.": "Het apparaat kon niet toetreden tot het LoRaWAN-netwerk: geen gateway beantwoordde zijn join-verzoek. Het blijft het proberen en slaat zijn records ondertussen op; ze komen aan zodra het toetreedt. Controleer de gateways bij het apparaat.",
    "The device reports its battery low. Plan a battery change before it stops sending.": "Het apparaat meldt een lage batterij. Plan een batterijwissel voordat het stopt met zenden.",
    "The tamper foil of the housing reports a break: the device may have been opened or damaged. Check the device and the animal.": "De sabotagefolie van de behuizing meldt een breuk: het apparaat kan geopend of beschadigd zijn. Controleer het apparaat en het dier.",
    "The device reports no service coverage: it could not reach the network at its last attempts and may hold records until it does.": "Het apparaat meldt geen netwerkdekking: het kon het netwerk bij zijn laatste pogingen niet bereiken en houdt records mogelijk vast tot het dat kan.",
    "The device's memory is full; the oldest stored records may be overwritten until the backlog is sent.": "Het geheugen van het apparaat is vol; de oudste opgeslagen records kunnen worden overschreven tot de achterstand is verzonden.",
    "The device's self test reported a fault. Watch the next messages; a fault that stays needs the device looked at.": "De zelftest van het apparaat meldde een fout. Volg de volgende berichten; een fout die blijft, vraagt om nazicht van het apparaat.",
    "The humidity inside the housing is above the device's bound; moisture may be getting in.": "De vochtigheid in de behuizing ligt boven de grens van het apparaat; er kan vocht binnendringen.",
    # the reset reasons
    "the firmware stopped responding and the watchdog restarted it": "de firmware reageerde niet meer en de watchdog heeft hem herstart",
    "the firmware restarted itself, as after a settings change or an update": "de firmware heeft zichzelf herstart, zoals na een instellingswijziging of een update",
    "the reset pin or the power was cycled": "de resetpin of de voeding is onderbroken",
    "the processor locked up and was reset": "de processor liep vast en is gereset",
    # event titles the drivers, the decoder and the reboot detection compose
    "Device rebooted ({reason})": "Apparaat herstart ({reason})",
    "Device rebooted": "Apparaat herstart",
    "External switch became active": "Externe schakelaar werd actief",
    "External switch became inactive": "Externe schakelaar werd inactief",
    "Device reports errors: {errors}": "Apparaat meldt fouten: {errors}",
    "Fence measurement failed: {result}": "Hekmeting mislukt: {result}",
    "Fix {km} km from the last one in {span}: flagged as an outlier": "Fix {km} km van de vorige in {span}: gemarkeerd als uitschieter",
    # the system checks
    "Worker {worker} has not reported for over 15 minutes": "Worker {worker} heeft zich meer dan 15 minuten niet gemeld",
    "{count} dead letters on {topic}": "{count} dead letters op {topic}",
    "{group} is {lag} messages behind on {topic}": "{group} loopt {lag} berichten achter op {topic}",
    # the shipped rule templates (shared/rules/templates.py)
    "{entity} left {feature}": "{entity} heeft {feature} verlaten",
    "{entity} entered {feature}": "{entity} is {feature} binnengegaan",
    "{entity} at {value} km/h inside {feature}": "{entity} met {value} km/u binnen {feature}",
    "{entity} at {value} km/h": "{entity} met {value} km/u",
    "{entity} has not reported for 12 hours": "{entity} heeft 12 uur niets gemeld",
    "{entity} within {value} m of {feature}": "{entity} binnen {value} m van {feature}",
    "{entity} battery at {value} V": "{entity} batterij op {value} V",
    "{entity} has not moved for 12 hours": "{entity} heeft 12 uur niet bewogen",
    "An entity leaves any geofence of the project.": "Een entiteit verlaat een geofence van het project.",
    "An entity enters any geofence of the project.": "Een entiteit gaat een geofence van het project binnen.",
    "Faster than 40 km/h inside a zone for 30 seconds (architecture 15.3).": "Sneller dan 40 km/u binnen een zone gedurende 30 seconden (architectuur 15.3).",
    "Faster than 60 km/h anywhere, from the speed the device reports with its fix (phase 37). Reminds every ten minutes while it stays. Scope the rule to the vehicle type so an animal's collar is never judged by it.": "Sneller dan 60 km/u waar dan ook, uit de snelheid die het apparaat bij zijn fix meldt (fase 37). Herinnert elke tien minuten zolang het duurt. Beperk de regel tot het voertuigtype, zodat de halsband van een dier er nooit op beoordeeld wordt.",
    "An entity has not reported for twelve hours. Checked every five minutes.": "Een entiteit heeft twaalf uur niets gemeld. Elke vijf minuten gecontroleerd.",
    "Battery voltage below 3.2 V. Reminds once a day while it stays low.": "Batterijspanning onder 3,2 V. Herinnert eenmaal per dag zolang ze laag blijft.",
    "An entity comes within 200 metres of any site of the project (a proximity rule, decision D140). Reminds once an hour while it stays.": "Een entiteit komt binnen 200 meter van een locatie van het project (een nabijheidsregel, beslissing D140). Herinnert eenmaal per uur zolang ze blijft.",
    "The accelerometer of the device has not changed between status messages for twelve hours (at least three messages), while the battery is fine. Checked hourly.": "De versnellingsmeter van het apparaat is twaalf uur niet veranderd tussen statusberichten (minstens drie berichten), terwijl de batterij in orde is. Elk uur gecontroleerd.",
    # the analysis warnings
    "No vegetation layer: this server has no environmental data provider yet. A server admin sets one up under Server admin, Environmental data.": "Geen vegetatielaag: deze server heeft nog geen omgevingsdataprovider. Een serverbeheerder richt er een in onder Serverbeheer, Omgevingsdata.",
    "The vegetation layer could not be read ({error}); the run is complete without it.": "De vegetatielaag kon niet worden gelezen ({error}); de analyse is compleet zonder die laag.",
    "{name}: only {share} percent of the weeks have a cloud-free observation.": "{name}: slechts {share} procent van de weken heeft een wolkenvrije waarneming.",
    "The subject changed device inside the period, on {when}.": "Het onderwerp wisselde binnen de periode van apparaat, op {when}.",
    "No value for '{key}' on {names}; they count as one animal each.": "Geen waarde voor '{key}' bij {names}; ze tellen elk als één dier.",
    "No fixes in the main period.": "Geen fixes in de hoofdperiode.",
    "No fixes in the comparison period.": "Geen fixes in de vergelijkingsperiode.",
    "{a} and {b} overlap by {ha} ha; time there counts in both.": "{a} en {b} overlappen {ha} ha; tijd daar telt in beide.",
    "{name}'s driver declares no health thresholds; the defaults apply.": "De driver van {name} geeft geen gezondheidsdrempels op; de standaardwaarden gelden.",
    "{name} sent nothing in the period.": "{name} heeft in de periode niets gestuurd.",
    "{name} sent nothing in the comparison period.": "{name} heeft in de vergelijkingsperiode niets gestuurd.",
    "{name}'s settings say a fix every {declared} ({source}), the device reports every {seen}: the settings Protect knows are stale; missed fixes are counted against what it does.": "De instellingen van {name} zeggen een fix elke {declared} ({source}), het apparaat meldt elke {seen}: de instellingen die Protect kent zijn verouderd; gemiste fixes worden geteld tegen wat het doet.",
    "{name}'s fix interval is not known and the fixes are too irregular to learn it ({share} percent near {interval}); missed fixes cannot be counted.": "Het fixinterval van {name} is niet bekend en de fixes zijn te onregelmatig om het te leren ({share} procent rond {interval}); gemiste fixes kunnen niet worden geteld.",
    "{name}'s fix interval is not known and too few fixes to learn it; missed fixes cannot be counted.": "Het fixinterval van {name} is niet bekend en er zijn te weinig fixes om het te leren; gemiste fixes kunnen niet worden geteld.",
    "The period holds fewer than three expected reports of {name}.": "De periode bevat minder dan drie verwachte meldingen van {name}.",
    "{n} records of {name} are held invalid (a clock ahead, or curated out).": "{n} records van {name} zijn ongeldig (een voorlopende klok, of weggecureerd).",
    "The fix interval of {n} devices is not known; their missed fixes cannot be counted.": "Het fixinterval van {n} apparaten is niet bekend; hun gemiste fixes kunnen niet worden geteld.",
    "The driver of {n} devices declares no health thresholds; the defaults apply to them.": "De driver van {n} apparaten geeft geen gezondheidsdrempels op; voor hen gelden de standaardwaarden.",
    "The period holds fewer than three expected reports of {n} devices.": "De periode bevat minder dan drie verwachte meldingen van {n} apparaten.",
    "{n} devices have records held invalid (a clock ahead, or curated out).": "{n} apparaten hebben ongeldige records (een voorlopende klok, of weggecureerd).",
    "{n} devices sent nothing in the period.": "{n} apparaten hebben in de periode niets gestuurd.",
    "{n} devices sent nothing in the comparison period.": "{n} apparaten hebben in de vergelijkingsperiode niets gestuurd.",
    # fences and traps (phase 32)
    "A fence monitor reads under 2 kV (phase 32). Reminds once a day while it stays down; the fence line's own status on the map follows the thresholds set on the line.": (
        "Een hekbewaker meet minder dan 2 kV (fase 32). Herinnert eenmaal per dag zolang het zo blijft; "
        "de status van de heklijn zelf op de kaart volgt de drempels die op de lijn zijn ingesteld."
    ),
    "{entity} reads {value} V on the fence": "{entity} meet {value} V op het hek",
    "A stretch of the fence line changed what it reads, from what the fence monitors on it last measured: live, low, down, or unknown when a monitor failed or fell silent.": (
        "Een stuk van de heklijn is anders gaan lezen, op grond van wat de hekbewakers erop het laatst "
        "hebben gemeten: onder spanning, laag, uitgevallen, of onbekend als een bewaker faalde of stil viel."
    ),
    "A fence monitor measured a voltage under the rule's threshold. The wire near it carries too little to hold an animal; check the energiser and the wire between them.": (
        "Een hekbewaker heeft een spanning onder de drempel van de regel gemeten. De draad bij hem voert te "
        "weinig om een dier tegen te houden; controleer het schrikdraadapparaat en de draad ertussen."
    ),
    "A fence monitor has not reported for the time the rule sets, so the stretch of fence it watches reads unknown. Check the device and the network near it.": (
        "Een hekbewaker heeft zo lang niets gemeld als de regel stelt, dus het stuk hek dat hij bewaakt "
        "leest onbekend. Controleer het apparaat en het netwerk in de buurt."
    ),
    "The switch on the trap says the door shut. Somebody has to go and look; a trap that stays shut holds whatever it caught.": (
        "De schakelaar op de val zegt dat de deur dicht is gegaan. Iemand moet gaan kijken; een val die "
        "dicht blijft houdt vast wat hij heeft gevangen."
    ),
    "The switch on the trap says the door is open again.": "De schakelaar op de val zegt dat de deur weer open is.",
    "The trap reads shut, from its switch, and stays so. Somebody has to go and look.": (
        "De val leest dicht, volgens zijn schakelaar, en blijft dat. Iemand moet gaan kijken."
    ),
    "A fence monitor has not reported for six hours (phase 32). Checked every five minutes; scope it to the Fence monitor type.": (
        "Een hekbewaker heeft zes uur niets gemeld (fase 32). Elke vijf minuten gecontroleerd; "
        "beperk de regel tot het type Hekbewaker."
    ),
    "{entity} has not reported for 6 hours": "{entity} heeft 6 uur niets gemeld",
    "A trap's door shut (phase 32, decision D266): somebody has to go and look. Reminds once a day while it stays shut.": (
        "De deur van een val is dichtgegaan (fase 32, besluit D266): iemand moet gaan kijken. "
        "Herinnert eenmaal per dag zolang hij dicht blijft."
    ),
    "{entity} is shut": "{entity} is dicht",
    "Trap {entity} closed": "Val {entity} dichtgegaan",
    "Trap {entity} opened": "Val {entity} opengegaan",
    "Fence {name} reads live near {stretch}": "Hek {name} staat onder spanning bij {stretch}",
    "Fence {name} reads low near {stretch}": "Hek {name} meet laag bij {stretch}",
    "Fence {name} reads down near {stretch}": "Hek {name} is uitgevallen bij {stretch}",
    "Fence {name} reads unknown near {stretch}": "Hek {name} is onbekend bij {stretch}",
    "Fence {name} reads live": "Hek {name} staat onder spanning",
    "Fence {name} reads low": "Hek {name} meet laag",
    "Fence {name} reads down": "Hek {name} is uitgevallen",
    "Fence {name} reads unknown": "Hek {name} is onbekend",
    # a scan for phones (decision D260)
    "Human presence": "Menselijke aanwezigheid",
    "{device} heard {n} human-worn Bluetooth device": (
        "{device} heeft {n} door een mens gedragen Bluetooth-apparaat gehoord"
    ),
    "{device} heard {n} human-worn Bluetooth devices": (
        "{device} heeft {n} door mensen gedragen Bluetooth-apparaten gehoord"
    ),
}
