#!/usr/bin/env python3
"""Scarica lo stato degli impianti da marcofabbrini.com e riscrive i file pubblici letti da Grok.

Variabili d'ambiente: FV_KEY (chiave del widget, nei Secrets del repository), FV_URL (opzionale).
Pubblica solo valori di sintesi: niente curve di potenza, niente chiavi, niente dati personali.
"""
import csv, json, os, sys, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

URL = os.environ.get("FV_URL", "https://marcofabbrini.com/api/fv-widget.php")
KEY = os.environ["FV_KEY"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOMI = {"casa_22": "CASA 22 (primo piano)", "casa_mg": "CASA M&G (secondo e terzo piano)"}


def r1(x):
    return None if x is None else round(float(x), 1)


def scarica():
    req = urllib.request.Request(URL, headers={"Authorization": "Bearer " + KEY, "User-Agent": "grock-aggiorna"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    if not d.get("ok"):
        raise SystemExit("risposta non valida dal sito")
    return d


def sintesi(i):
    o = i.get("oggi") or {}
    return {
        "id": i["id"],
        "nome": NOMI.get(i["id"], i.get("nome", i["id"])),
        "batteria_percento": r1(i.get("soc")),
        "potenza_ora_kw": {
            "produzione_fotovoltaico": r1(i.get("pv_kw")),
            "consumo_casa": r1(i.get("casa_kw")),
            "rete": r1(i.get("rete_kw")),
            "batteria": r1(i.get("batteria_kw")),
        },
        "energia_oggi_kwh": {
            "produzione": r1(o.get("pv")), "consumo": r1(o.get("load")),
            "immessa_in_rete": r1(o.get("export")), "prelevata_dalla_rete": r1(o.get("import")),
            "batteria_caricata": r1(o.get("charge")), "batteria_scaricata": r1(o.get("discharge")),
        },
        "produzione_ieri_kwh": r1(i.get("ieri_pv")),
        "produzione_mese_kwh": r1(i.get("mese_pv")),
    }


def sintesi_casa(c):
    """Luci accese (senza Laboratorio) e gas (riscaldamento e ACS), letti da Home Assistant tramite il sito. None se non ancora disponibili."""
    if not isinstance(c, dict):
        return None
    g = c.get("gas") or {}

    def tipo(k):
        x = g.get(k) or {}
        return {"oggi": r2(x.get("oggi")), "mese": r2(x.get("mese")), "contatore_totale": r2(x.get("totale"))}

    ris, acs = tipo("riscaldamento"), tipo("acs")

    def somma(k):
        a, b = ris[k], acs[k]
        return None if a is None and b is None else round((a or 0) + (b or 0), 2)

    return {
        "luci_accese_escluso_laboratorio": c.get("luci_accese"),
        "gas": {"unita": g.get("unita") or "m3", "riscaldamento": ris, "acs": acs,
                "totale": {"oggi": somma("oggi"), "mese": somma("mese")}},
        "letto_alle_utc": c.get("ts"),
    }


def r2(x):
    return None if x is None else round(float(x), 2)


def aggiorna_storico(imps, giorno):
    path = os.path.join(ROOT, "data", "storico_giornaliero.csv")
    campi = ["data", "impianto", "produzione_kwh", "consumo_kwh", "immessa_kwh", "prelevata_kwh"]
    righe = {}
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                righe[(r["data"], r["impianto"])] = r
    for i in imps:
        e = i["energia_oggi_kwh"]
        righe[(giorno, i["id"])] = {"data": giorno, "impianto": i["id"], "produzione_kwh": e["produzione"],
                                    "consumo_kwh": e["consumo"], "immessa_kwh": e["immessa_in_rete"], "prelevata_kwh": e["prelevata_dalla_rete"]}
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campi)
        w.writeheader()
        for k in sorted(righe):
            w.writerow(righe[k])


def v(x, u):
    return "n.d." if x is None else f"{x} {u}"


def readme(imps, quando, casa=None):
    t = [
        "# GROCK · Impianti fotovoltaici di Marco Fabbrini", "",
        f"Ultimo aggiornamento: **{quando}** (ora italiana). Si aggiorna ogni 5 minuti circa.", "",
        "Questi dati descrivono i due impianti fotovoltaici con accumulo dell'edificio. "
        "Convenzioni: rete positiva = energia prelevata dalla rete, negativa = energia immessa; "
        "batteria positiva = in carica, negativa = in scarica.", "",
    ]
    for i in imps:
        p, e = i["potenza_ora_kw"], i["energia_oggi_kwh"]
        t += [
            f"## {i['nome']}", "",
            f"- Batteria: {v(i['batteria_percento'], '%')}",
            f"- Produzione fotovoltaico adesso: {v(p['produzione_fotovoltaico'], 'kW')}",
            f"- Consumo della casa adesso: {v(p['consumo_casa'], 'kW')}",
            f"- Rete adesso: {v(p['rete'], 'kW')}",
            f"- Batteria adesso: {v(p['batteria'], 'kW')}",
            f"- Oggi: produzione {v(e['produzione'], 'kWh')}, consumo {v(e['consumo'], 'kWh')}, "
            f"immessi in rete {v(e['immessa_in_rete'], 'kWh')}, prelevati dalla rete {v(e['prelevata_dalla_rete'], 'kWh')}",
            f"- Produzione ieri: {v(i['produzione_ieri_kwh'], 'kWh')}",
            f"- Produzione del mese finora: {v(i['produzione_mese_kwh'], 'kWh')}", "",
        ]
    if casa:
        g = casa["gas"]
        u = g["unita"].replace("m3", "m³")
        luci = casa["luci_accese_escluso_laboratorio"]
        t += [
            "## Casa", "",
            f"- Luci accese adesso (escluso il Laboratorio): {'n.d.' if luci is None else luci}", "",
            "### Gas", "",
            f"- Riscaldamento: oggi {v(g['riscaldamento']['oggi'], u)}, nel mese {v(g['riscaldamento']['mese'], u)}",
            f"- Acqua calda sanitaria (ACS): oggi {v(g['acs']['oggi'], u)}, nel mese {v(g['acs']['mese'], u)}",
            f"- Totale gas: oggi {v(g['totale']['oggi'], u)}, nel mese {v(g['totale']['mese'], u)}",
            f"- Letture dei contatori: riscaldamento {v(g['riscaldamento']['contatore_totale'], u)}, ACS {v(g['acs']['contatore_totale'], u)}", "",
        ]
    t += ["Dati completi in formato macchina: [`data/latest.json`](data/latest.json). "
          "Storico dei totali giornalieri: [`data/storico_giornaliero.csv`](data/storico_giornaliero.csv).", ""]
    return "\n".join(t)


def main():
    d = scarica()
    now = datetime.now(ZoneInfo("Europe/Rome"))
    imps = [sintesi(i) for i in d.get("impianti", [])]
    if not imps:
        sys.exit("nessun impianto nella risposta")
    quando = now.strftime("%d/%m/%Y %H:%M")
    casa = sintesi_casa(d.get("casa"))
    out = {"aggiornato": now.isoformat(timespec="minutes"), "impianti_online": bool(d.get("online")), "impianti": imps, "casa": casa}
    with open(os.path.join(ROOT, "data", "latest.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    aggiorna_storico(imps, now.strftime("%Y-%m-%d"))
    with open(os.path.join(ROOT, "README.md"), "w") as f:
        f.write(readme(imps, quando, casa))


if __name__ == "__main__":
    main()
