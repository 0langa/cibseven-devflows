# Demo in fünf Minuten

Vom kalten Start bis zum fertigen Release in unter zehn Minuten, dazu ein Fünf-Minuten-Skript zum
Vorführen.

Englische Fassung: [DEMO.md](DEMO.md).

## Vor der Demo

Der Reihe nach ausführen. Der ganze Block dauert etwa drei Minuten, das meiste davon Warten auf die
Engine.

**1. Engine starten.**

```bash
docker compose -f engine/docker-compose.yml up -d
```

**2. Projekt installieren.**

```bash
uv sync
```

**3. Prozess und Entscheidungstabelle deployen.**

```bash
curl -s -X POST http://localhost:8080/engine-rest/deployment/create -F "deployment-name=cibseven-devflows" -F "release.bpmn=@processes/release.bpmn" -F "release-policy.dmn=@processes/release-policy.dmn"
```

**4. Alles mit einem Befehl prüfen.**

```bash
uv run devflows-doctor
```

Jede Zeile muss `ok` sagen. Wenn nicht, steht dort auch, was zu tun ist. Das ist zugleich ein guter
erster Zug vor Publikum: Es zeigt das gesamte Setup in sieben Zeilen.

**5. Worker in einem eigenen Terminal starten und sichtbar lassen.**

```bash
uv run devflows-worker
```

Er meldet `Waiting for work on: devflows.gates, devflows.notes, devflows.tag, devflows.publish,
devflows.untag`. Dieses Terminal so hinstellen, dass das Publikum es sieht: Hier wird sichtbar, dass
wirklich gearbeitet wird.

**6. Zwei Browser-Tabs öffnen**, beide angemeldet unter <http://localhost:8080/webapp/> als
`demo` / `demo`:

- **Prozesse**: <http://localhost:8080/webapp/#/seven/auth/processes/list> , auf `Release ritual`
- **Aufgaben**: <http://localhost:8080/webapp/#/seven/auth/tasks> , Filter **My Group Tasks**

Dieses Front-End verwenden, nicht die älteren Webapps unter `/camunda/app/`. CIB seven 2.2 liefert
die zwar weiterhin aus, aber dort steht auf jeder Seite ein rotes Banner, dass die Oberfläche
veraltet ist und nicht mehr unterstützt wird.

**7. Claude Code** in diesem Repository geöffnet haben, mit geladenem Plugin.

## Das Skript

### 0:00 – 0:45 · Worum es geht

> CIB seven ist ein Open-Source-Fork der Camunda-7-BPM-Engine, gepflegt von CIB. Dieses Projekt
> nimmt etwas, das ich jede Woche von Hand mache, nämlich ein Release schneiden, und lässt es als
> BPMN-Prozess darauf laufen.
>
> Ein Release ist ein Prozess: Tests laufen lassen, draufschauen, entscheiden, taggen,
> veröffentlichen. Mittendrin steht eine menschliche Entscheidung. Genau für diese Form von Ablauf
> ist eine Process Engine gebaut, also habe ich ihn dort hineingelegt.

### 0:45 – 1:45 · Der Prozess

`Release ritual` unter **Prozesse** öffnen und das Diagramm zeigen.

> Drei Arten von Kästen. Die mit dem Zahnrad sind **External Tasks**: Die Engine führt selbst nichts
> aus, sie veröffentlicht Arbeit zu einem Topic, und ein Worker auf meinem Rechner holt sie sich.
> Genau deshalb ist es unbedenklich, eine Process Engine einen Entwicklerrechner steuern zu lassen.
>
> Der Kasten in der Mitte ist ein **User Task**. Dort hält der Prozess an und wartet auf einen
> Menschen. Er wartet auch über einen Neustart hinweg, weil der Zustand in der Datenbank liegt und
> nicht in einem Skript. Und er hat einen Timer: Ein Release, das niemand beantwortet, lehnt sich
> selbst ab, statt ewig offen zu bleiben.
>
> Der Kasten davor ist ein **Business Rule Task**. Er ruft eine DMN-Entscheidungstabelle auf, die
> entscheidet, ob überhaupt ein Mensch gebraucht wird.

Dann unten rechts zeigen.

> Und das ist der Teil, den ich am liebsten mag. Wenn das Veröffentlichen fehlschlägt, nachdem der
> Tag schon angelegt wurde, wirft dieses Error Boundary Event eine **Kompensation**. Die führt den
> Undo-Handler aus und löscht den Tag wieder. Ein Release, das schiefgeht, lässt nicht die Hälfte
> von sich zurück.

### 1:45 – 2:30 · Die Regel ist Fachlichkeit, kein Code

`processes/release-policy.dmn` im Camunda Modeler öffnen, oder einfach die Tabelle aus der README
zeigen.

> Ein Patch-Release mit grünen Gates geht raus, ohne dass jemand gefragt wird. Alles Größere fragt
> mich. Diese Regel ist eine DMN-Tabelle und kein `if` in meinem Python. Wenn das Team morgen
> entscheidet, dass auch Minor-Releases automatisch rausgehen dürfen, ändert jemand eine Zelle und
> deployt neu. Kein Code-Review, kein Deployment meines Workers.

### 2:30 – 3:30 · Ein Release aus Claude Code starten

In Claude Code:

```
/devflows:release 0.3.0
```

Claude führt `doctor` aus, listet die Gates auf und startet einen Lauf mit `dry_run=true`.

Dabei auf das Worker-Terminal zeigen.

> Da läuft gerade die echte Testsuite dieses Repositories und der echte Linter, so wie sie in
> `devflows.yaml` stehen. Danach entwirft er die Release Notes: Er sammelt die Commits seit dem
> letzten Tag und lässt sie von der lokalen Claude-CLI schreiben. Die Engine schaut nur zu.

Zur Prozessansicht wechseln und aktualisieren.

> Das Token ist bei der Freigabe stehen geblieben, weil 0.3.0 ein Minor-Release ist und die
> Entscheidungstabelle sagt: Bei einem Minor-Release muss ein Mensch ran.

### 3:30 – 4:30 · Als Mensch freigeben

Zu **Aufgaben**, **My Group Tasks** wechseln und die Aufgabe übernehmen.

> Hier ist dieselbe Aufgabe von der anderen Seite. Sie hängt an der Gruppe `camunda-admin` und nicht
> an einer einzelnen Person, also kann sie jeder aus der Gruppe übernehmen.
>
> Im Formular stehen die Ergebnisse der Gates und die Release Notes, die die KI entworfen hat. Ich
> kann sie hier direkt überschreiben, und was ich freigebe, wird veröffentlicht. Genau so möchte ich
> KI in einem Workflow haben: Sie macht den mühsamen Teil, ein Mensch verantwortet das Ergebnis, und
> der Prozess ist das, was diese Reihenfolge erzwingt. Claude kann dieses Release starten und
> beobachten, aber nicht freigeben, weil das Freigeben ein Schritt im Prozess ist und keine Regel in
> einem Prompt.

**Approve this release** anhaken, abschicken, und wieder auf das Worker-Terminal zeigen, während
Tag- und Publish-Schritt laufen.

### 4:30 – 5:00 · Das Ergebnis

Die abgeschlossene Instanz unter **Prozesse** in der Historie zeigen.

> Abgeschlossen. Alle Variablen sind da: welche Gates gelaufen sind und was sie ausgegeben haben,
> was die Regel entschieden hat und warum, wer freigegeben und was er geändert hat, der Tag und die
> Release-URL.

Dann:

> Und das ist kein Demo-Repository. Version 0.1.0 dieses Projekts wurde von genau diesem Prozess
> veröffentlicht, angewendet auf sich selbst, und 0.2.0 genauso.

<https://github.com/0langa/cibseven-devflows/releases> öffnen.

## Optional: Timer oder Kompensation zeigen

Beides geht schnell und kommt gut an, wenn Zeit oder eine Nachfrage da ist.

**Der Timer.** Einen Lauf mit zwei Minuten Frist starten und ihn einfach nicht beantworten:

```bash
uv run pytest tests/integration/test_live_release.py -k timer -q
```

Oder von Hand einen Lauf mit `approval_timeout` auf `PT2M` starten und zusehen, wie die Instanz sich
selbst beendet.

**Kompensation.** Die Integrationstests beweisen das gegen die echte Engine, auf einem
Wegwerf-Repository: Der Tag wird angelegt, der Push scheitert mangels Remote, und danach ist der Tag
wieder weg.

```bash
uv run pytest tests/integration/test_live_release.py -k compensat -q
```

## Argumente für das Gespräch

**CIB seven ist ein Camunda-7-Fork.** Es ist eine gepflegte Open-Source-Fortführung von Camunda 7:
dieselbe Engine, dieselbe `/engine-rest`-API, dieselben Webapps. Alles in diesem Repository ist
normales Camunda-7-BPMN und -DMN mit dem `camunda`-Extension-Namespace und öffnet sich unverändert
im Camunda Modeler 5.x als Camunda-7-Datei. Nichts daran ist ein Sonderfall.

**Das External-Task-Pattern.** Die Engine hält den Zustand und veröffentlicht Arbeit zu Topics.
Worker rufen `fetchAndLock`, erledigen die Arbeit dort, wo sie stehen, und melden `complete`,
`failure` oder `bpmnError` zurück. Die Engine braucht nie Zugangsdaten für meinen Rechner, mein
Rechner muss von der Engine aus nie erreichbar sein, und ein abgestürzter Worker wird zu einem
sichtbaren Incident statt zu einem verlorenen Schritt. Dieses Projekt nutzt schlichtes HTTP mit
`httpx` statt einer Client-Bibliothek, sodass das Pattern in etwa achtzig Zeilen Code sichtbar ist.

**Failure gegen Error.** Das ist nicht dasselbe, und die Engine behandelt es unterschiedlich. Ein
Netzwerkaussetzer ist ein *Failure*: Der Worker meldet ihn mit verbleibenden Retries und einem
Backoff, und erst ein aufgebrauchter Zähler erzeugt einen Incident. Ein abgelehntes Veröffentlichen
ist ein *BPMN Error*: Beim nächsten Versuch wird es genauso wenig klappen, also fängt das Diagramm
ihn ab und kompensiert. Diese Unterscheidung sauber hinzubekommen ist der größte Teil dessen, was
einen Workflow im Betrieb überlebensfähig macht.

**Mensch im Ablauf.** Die Freigabe ist ein echter BPMN User Task mit generiertem Formular. Sie ist
dauerhaft, sie ist nachvollziehbar, und sie lässt sich an zwei Stellen beantworten: in der
Weboberfläche oder über das MCP-Tool `approve_gate`. Dieselbe Aufgabe, dieselben Variablen, egal
wie.

**Bezug zu CIB seven 2.2.** Dieses Release bringt einen AI Agent Connector und MCP-Unterstützung
mit: Im Container steht `AI_AGENT_ENABLED=true` standardmäßig auf an, ein Prozess kann also einen
KI-Agenten als Schritt aufrufen. Dieses Projekt macht beide Hälften. Die KI steuert den Prozess von
außen über MCP, und der Prozess ruft von innen eine KI für die Release Notes auf — mit einem
Menschen zwischen diesem Entwurf und allem, was öffentlich wird.

**Warum kein Shell-Skript.** Ein Skript hat kein Gedächtnis, keine Historie und keinen Ort zum
Warten. Dauerhaftes Warten, ein Prüfpfad, eine Weboberfläche für den menschlichen Schritt, eine
Entscheidungstabelle, die jeder ändern kann, Retries, Incidents und eine Kompensation, die Arbeit
zurücknimmt: Das alles kommt daher, den Prozess in eine Engine zu legen statt in eine Datei.

## Wenn etwas schiefgeht

| Symptom | Ursache | Abhilfe |
| --- | --- | --- |
| Irgendetwas | Unbekannt | Zuerst `uv run devflows-doctor`; es benennt das Problem |
| Ein Lauf startet, aber nichts passiert | Der Worker läuft nicht | `uv run devflows-worker` in einem zweiten Terminal |
| Der Lauf war fertig, ohne mich zu fragen | Die Regel hat automatisch freigegeben | Bei einem Patch-Release erwartet; `policy_reason` sagt es |
| Die Aufgabe kam nie und der Lauf ist beendet | Der Freigabe-Timer ist abgelaufen | Neu starten mit größerem `approval_timeout` |
| Ein Lauf hängt | Ein Incident | `get_run` zeigt ihn; Ursache beheben, dann `retry_run` |
| Die Aufgabe taucht nicht auf | Falscher Filter | **My Group Tasks** wählen, nicht **My Tasks** |
| Die Engine stürzt beim Start mit `AccessDeniedException` ab | Der Dienst `cibseven-init` lief nicht | `docker compose up -d` benutzen; siehe [engine/README.md](../engine/README.md) |

## Zwischen zwei Demos zurücksetzen

Abgeschlossene Instanzen bleiben in der Historie, was meistens erwünscht ist. Für eine saubere
Engine:

```bash
docker compose -f engine/docker-compose.yml down -v
```

```bash
docker compose -f engine/docker-compose.yml up -d
```

Danach Prozess und Entscheidung erneut deployen. Ein Dry Run legt nie einen Tag an, im Repository
selbst ist also nichts aufzuräumen.

## Die Releases, die dieser Prozess geschnitten hat

Fürs Protokoll, damit die Behauptung überprüfbar ist und nicht geglaubt werden muss.

| Version | Prozessinstanz | Anmerkung |
| --- | --- | --- |
| v0.1.0 | `0e656a8f-9e47-11f1-be39-22fc550e6cab` | Freigegeben von `demo` in der Weboberfläche, Kommentar "Good release" |
| v0.2.0 | `665766a1-9f06-11f1-be39-22fc550e6cab` | Notes von `claude` entworfen; die Regel verlangte eine Freigabe, weil 0.2.0 ein Minor-Release ist |

Der Text von v0.2.0 musste hinterher korrigiert werden: Das Freigabeformular hat die mehrzeiligen
Notes in eine Zeile gequetscht, und das Modell hat Prosa drumherum geschrieben. Beides ist behoben
und durch Tests abgedeckt, aber das Release war zu dem Zeitpunkt schon öffentlich.

Jede Instanz bleibt so lange in der Historie, wie ihre `historyTimeToLive` von 30 Tagen es zulässt.
