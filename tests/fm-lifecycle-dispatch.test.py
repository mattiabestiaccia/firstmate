#!/usr/bin/python3
"""Prove di fm-lifecycle: modello ed effort risolti da config/crew-dispatch.json (S3, S4).

Lancio, anche dalla sandbox degli agenti:
  /usr/bin/python3 -B ~/firstmate/tests/fm-lifecycle-dispatch.test.py

Prova bin/fm-lifecycle di questo repository, o il file indicato in FM_LIFECYCLE.
La prima prova legge il vero ~/firstmate/config/crew-dispatch.json: fallisce se il
file e' cambiato senza aggiornare la TABELLA di fm-lifecycle.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
QUI = os.path.dirname(os.path.abspath(__file__))
LIFECYCLE = os.environ.get("FM_LIFECYCLE") or os.path.normpath(os.path.join(QUI, "..", "bin", "fm-lifecycle"))


def carica():
    loader = importlib.machinery.SourceFileLoader("fm_lifecycle", LIFECYCLE)
    spec = importlib.util.spec_from_loader("fm_lifecycle", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


R = carica()
VERO_DISPATCH = R.CREW_DISPATCH

# Copia delle regole di oggi, nella forma del file, per le prove con file finti.
REGOLE = [
    {"when": "Ship task that is not simple or mechanical, harness Claude: ...",
     "use": {"harness": "claude", "model": "opus", "effort": "high"}, "why": "..."},
    {"when": "Ship task that is simple or mechanical, harness Claude (...).",
     "use": {"harness": "claude", "model": "sonnet", "effort": "medium"}},
    {"when": "Scout task, harness Claude (...).",
     "use": {"harness": "claude", "model": "sonnet", "effort": "medium"}},
    {"when": "Ship task that is not simple or mechanical, harness Pi: ...",
     "use": {"harness": "pi", "model": "openai/gpt-6.1-sol", "effort": "medium"}},
    {"when": "Ship task that is simple or mechanical, harness Pi (...).",
     "use": {"harness": "pi", "model": "openai/gpt-6-luna", "effort": "medium"}},
    {"when": "Scout task, harness Pi (...).",
     "use": {"harness": "pi", "model": "openai/gpt-6-luna", "effort": "medium"}},
    {"when": "Fix, debug or review task, harness Pi: ...",
     "use": {"harness": "pi", "model": "openai/gpt-6.1-sol", "effort": "medium"}},
    {"when": "Fix, debug or review task, harness Claude (...).",
     "use": {"harness": "claude", "model": "opus", "effort": "high"}},
]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fm-lifecycle-test.")
        self.vecchi = {k: getattr(R, k) for k in ("CREW_DISPATCH", "STATE", "LOG_DIR", "SCRIPT")}
        R.STATE = os.path.join(self.tmp, "state")
        os.mkdir(R.STATE)
        R.LOG_DIR = os.path.join(self.tmp, "log")
        R.SCRIPT = {}
        for nome in ("spawn", "control", "teardown"):
            p = os.path.join(self.tmp, "fm-%s.sh" % nome)
            with open(p, "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(p, 0o755)
            R.SCRIPT[nome] = p
        self.progetto = os.path.join(self.tmp, "progetto")
        os.mkdir(self.progetto)
        self.dispatch(REGOLE)

    def tearDown(self):
        for k, v in self.vecchi.items():
            setattr(R, k, v)
        shutil.rmtree(self.tmp)

    def dispatch(self, regole, testo=None):
        R.CREW_DISPATCH = os.path.join(self.tmp, "crew-dispatch.json")
        with open(R.CREW_DISPATCH, "w") as f:
            f.write(testo if testo is not None else json.dumps({"rules": regole}))

    def meta(self, tid, **campi):
        with open(os.path.join(R.STATE, tid + ".meta"), "w") as f:
            for k, v in campi.items():
                f.write("%s=%s\n" % (k, v))

    def spawn(self, *opz):
        return R.comando_spawn(["t1", self.progetto] + list(opz))[3:]

    def relaunch(self, *opz, tid="t1"):
        return R.comando_control([tid, "relaunch", "--note", "nota"] + list(opz))[3:]

    def rifiuta(self, fn, *args, contiene="", **kw):
        with self.assertRaises(R.Rifiuto) as ctx:
            fn(*args, **kw)
        self.assertIn(contiene, str(ctx.exception))

    def profilo(self, opz):
        return opz[opz.index("--model") + 1], opz[opz.index("--effort") + 1]


class TabellaContraFile(Base):
    def test_il_vero_crew_dispatch_corrisponde_alla_tabella(self):
        self.assertTrue(os.path.isfile(VERO_DISPATCH), "manca %s" % VERO_DISPATCH)
        self.assertEqual(R.tabella_dal_file(VERO_DISPATCH), R.TABELLA,
                         "crew-dispatch.json e' cambiato: aggiorna TABELLA in bin/fm-lifecycle")

    def test_le_regole_finte_corrispondono(self):
        R.controlla_tabella()

    def test_un_modello_cambiato_rifiuta(self):
        regole = json.loads(json.dumps(REGOLE))
        regole[2]["use"]["model"] = "haiku"
        self.dispatch(regole)
        self.rifiuta(R.controlla_tabella, contiene="non corrispondono")
        self.rifiuta(self.spawn, "--scout", contiene="non corrispondono")

    def test_una_regola_in_piu_rifiuta(self):
        self.dispatch(REGOLE + [{"when": "Docs task, harness Claude.",
                                 "use": {"harness": "claude", "model": "haiku", "effort": "low"}}])
        self.rifiuta(R.controlla_tabella, contiene="non sa tradurre")

    def test_una_regola_doppia_rifiuta(self):
        self.dispatch(REGOLE + [REGOLE[0]])
        self.rifiuta(R.controlla_tabella, contiene="due regole")

    def test_una_regola_in_meno_rifiuta(self):
        self.dispatch(REGOLE[1:])
        self.rifiuta(R.controlla_tabella, contiene="non corrispondono")

    def test_file_assente_o_rotto_rifiuta(self):
        self.dispatch(None, testo="{rotto")
        self.rifiuta(R.controlla_tabella, contiene="non riesco a leggere")
        os.unlink(R.CREW_DISPATCH)
        self.rifiuta(R.controlla_tabella, contiene="non riesco a leggere")
        self.rifiuta(self.spawn, "--complesso", contiene="non riesco a leggere")


class Spawn(Base):
    """Le righe Claude, con --harness claude esplicito (dal 18 novembre 2026 il default e' Pi)."""

    def spawn(self, *opz):
        return super().spawn("--harness", "claude", *opz)

    def test_ship_senza_tipo_rifiuta(self):
        self.rifiuta(self.spawn, "--mode", "local-only", "--yolo", "off", contiene="--semplice")
        self.rifiuta(self.spawn, "--effort", "high", contiene="--complesso")
        self.rifiuta(self.spawn, "--model", "opus", contiene="--complesso")

    def test_ship_complesso(self):
        opz = self.spawn("--mode", "local-only", "--yolo", "off", "--complesso")
        self.assertEqual(self.profilo(opz), ("opus", "high"))
        self.assertIn("--harness", opz)
        self.assertNotIn("--complesso", opz)

    def test_ship_semplice(self):
        opz = self.spawn("--semplice")
        self.assertEqual(self.profilo(opz), ("sonnet", "medium"))
        self.assertNotIn("--semplice", opz)

    def test_semplice_e_complesso_insieme_rifiuta(self):
        self.rifiuta(self.spawn, "--semplice", "--complesso", contiene="si escludono")
        self.rifiuta(self.spawn, "--complesso", "--correzione", contiene="si escludono")

    def test_ship_come_la_riga_non_vuole_motivo(self):
        self.assertEqual(self.profilo(self.spawn("--complesso", "--model", "opus", "--effort", "high")),
                         ("opus", "high"))
        self.assertEqual(self.profilo(self.spawn("--semplice", "--effort", "medium")), ("sonnet", "medium"))

    def test_ship_fuori_riga_vuole_motivo(self):
        self.rifiuta(self.spawn, "--semplice", "--model", "opus", contiene="invece di sonnet/medium")
        self.rifiuta(self.spawn, "--complesso", "--effort", "xhigh", contiene="invece di opus/high")
        self.rifiuta(self.spawn, "--complesso", "--model", "sonnet", contiene="--dispatch-override")
        opz = self.spawn("--semplice", "--model", "opus", "--dispatch-override", "chiesto da Mattia")
        self.assertEqual(self.profilo(opz), ("opus", "medium"))
        opz = self.spawn("--complesso", "--effort", "xhigh", "--dispatch-override", "chiesto da Mattia")
        self.assertEqual(self.profilo(opz), ("opus", "xhigh"))

    def test_ship_senza_tipo_a_mano_vuole_sempre_motivo(self):
        # Il caso della revisione di Meta: cosi' herdr-pane-resize ripartirebbe su Haiku.
        self.rifiuta(self.spawn, "--model", "haiku", "--effort", "low", contiene="scritti a mano")
        self.rifiuta(self.spawn, "--model", "opus", "--effort", "high", contiene="--dispatch-override")
        opz = self.spawn("--model", "haiku", "--effort", "low", "--dispatch-override", "chiesto da Mattia")
        self.assertEqual(self.profilo(opz), ("haiku", "low"))

    def test_ship_a_mano_con_motivo_non_legge_il_file(self):
        os.unlink(R.CREW_DISPATCH)
        opz = self.spawn("--model", "opus", "--effort", "max", "--dispatch-override", "chiesto da Mattia")
        self.assertEqual(self.profilo(opz), ("opus", "max"))

    def test_scout_dalla_tabella(self):
        self.assertEqual(self.profilo(self.spawn("--scout")), ("sonnet", "medium"))

    def test_scout_con_effort_ammessi(self):
        self.assertEqual(self.profilo(self.spawn("--scout", "--effort", "high")), ("sonnet", "high"))
        self.assertEqual(self.profilo(self.spawn("--scout", "--effort", "low")), ("sonnet", "low"))

    def test_scout_su_altro_modello_vuole_motivo(self):
        self.rifiuta(self.spawn, "--scout", "--model", "opus", contiene="--dispatch-override")
        self.rifiuta(self.spawn, "--scout", "--model", "haiku", contiene="--dispatch-override")
        opz = self.spawn("--scout", "--model", "opus", "--dispatch-override", "confronto chiesto da Mattia")
        self.assertEqual(self.profilo(opz), ("opus", "medium"))
        self.assertEqual(opz[opz.index("--dispatch-override") + 1], "confronto chiesto da Mattia")

    def test_scout_con_effort_alto_vuole_motivo(self):
        self.rifiuta(self.spawn, "--scout", "--effort", "xhigh", contiene="effort xhigh")
        self.rifiuta(self.spawn, "--scout", "--effort", "max", contiene="effort max")
        opz = self.spawn("--scout", "--effort", "xhigh", "--dispatch-override", "verifica lunga")
        self.assertEqual(self.profilo(opz), ("sonnet", "xhigh"))

    def test_scout_non_vuole_semplice_o_complesso(self):
        self.rifiuta(self.spawn, "--scout", "--semplice", contiene="non per uno scout")

    def test_fable_solo_con_motivo(self):
        for m in ("fable", "Fable", "claude-fable-5-2"):
            self.rifiuta(self.spawn, "--complesso", "--model", m, contiene="Fable")
            self.rifiuta(self.spawn, "--model", m, "--effort", "high", contiene="Fable")
            self.rifiuta(self.spawn, "--complesso", "--model", m, "--effort", "high", contiene="Fable")
            self.rifiuta(self.spawn, "--scout", "--model", m, contiene="Fable")
        opz = self.spawn("--complesso", "--model", "fable", "--dispatch-override", "Mattia: usa Fable")
        self.assertEqual(self.profilo(opz), ("fable", "high"))

    def test_motivo_non_valido_rifiuta(self):
        for m in ("", "   ", "due\nrighe", "x" * 501):
            self.rifiuta(self.spawn, "--scout", "--model", "opus", "--dispatch-override", m,
                         contiene="--dispatch-override")

    def test_motivo_con_accenti_passa(self):
        opz = self.spawn("--scout", "--model", "opus", "--dispatch-override", "perché serve più profondità")
        self.assertIn("perché serve più profondità", opz)

    def test_opzione_ripetuta_rifiuta(self):
        self.rifiuta(self.spawn, "--complesso", "--model", "sonnet", "--model", "opus", contiene="ripetuta")

    def test_un_valore_uguale_a_un_opzione_non_inganna(self):
        opz = self.spawn("--complesso", "--dispatch-override", "--model")
        self.assertEqual(opz, ["--harness", "claude", "--dispatch-override", "--model",
                               "--model", "opus", "--effort", "high"])


class YoloElenco(Base):
    """--yolo on solo per i progetti con origin nell'elenco del merge automatico (S6, S30)."""

    def setUp(self):
        super().setUp()
        self.vecchi_yolo = (R.YOLO_RADICE, R.YOLO_ELENCO)
        R.YOLO_RADICE = os.path.join(self.tmp, "projects")
        os.mkdir(R.YOLO_RADICE)
        R.YOLO_ELENCO = os.path.join(self.tmp, "merge-automatico.txt")
        with open(R.YOLO_ELENCO, "w") as f:
            f.write("# commento\nmattiabestiaccia/postit\n")
        self.postit = self.repo("postit", "https://github.com/mattiabestiaccia/postit.git")

    def tearDown(self):
        R.YOLO_RADICE, R.YOLO_ELENCO = self.vecchi_yolo
        super().tearDown()

    def repo(self, nome, origin, radice=None):
        p = os.path.join(radice or R.YOLO_RADICE, nome)
        subprocess.run(["/usr/bin/git", "init", "-q", p], check=True)
        subprocess.run(["/usr/bin/git", "-C", p, "remote", "add", "origin", origin], check=True)
        return p

    def yolo(self, progetto):
        return R.comando_spawn(["t1", progetto, "--complesso", "--yolo", "on"])

    def test_yolo_off_ovunque(self):
        self.assertIn("off", self.spawn("--complesso", "--yolo", "off"))

    def test_yolo_on_in_elenco_passa(self):
        opz = self.yolo(self.postit)
        self.assertEqual(opz[opz.index("--yolo") + 1], "on")

    def test_origin_senza_git_e_in_maiuscole_passa(self):
        self.yolo(self.repo("p2", "https://github.com/MattiaBestiaccia/Postit"))

    def test_origin_fuori_elenco_rifiuta(self):
        self.rifiuta(self.yolo, self.repo("bruvish", "https://github.com/mattiabestiaccia/bruvish.git"),
                     contiene="non e' nell'elenco")

    def test_progetto_fuori_da_projects_rifiuta(self):
        fuori = self.repo("postit", "https://github.com/mattiabestiaccia/postit.git", radice=self.tmp)
        self.rifiuta(self.yolo, fuori, contiene="deve stare in")

    def test_origin_simile_rifiuta(self):
        self.rifiuta(self.yolo, self.repo("p3", "https://github.com/mattiabestiaccia/postit-voci.git"),
                     contiene="non e' nell'elenco")

    def test_elenco_assente_rifiuta(self):
        os.remove(R.YOLO_ELENCO)
        self.rifiuta(self.yolo, self.postit, contiene="non leggibile")

    def test_yolo_valore_ignoto_rifiuta(self):
        self.rifiuta(self.spawn, "--complesso", "--yolo", "sempre", contiene="ammette solo")


class HarnessPi(Base):
    """S255 (18 novembre 2026): worker Pi ammessi, Codex e gli altri no."""

    def test_spawn_pi_ship_semplice(self):
        opz = self.spawn("--harness", "pi", "--semplice")
        self.assertEqual(self.profilo(opz), ("openai/gpt-6-luna", "medium"))

    def test_spawn_pi_ship_complesso(self):
        opz = self.spawn("--harness", "pi", "--complesso")
        self.assertEqual(self.profilo(opz), ("openai/gpt-6.1-sol", "medium"))

    def test_spawn_pi_scout(self):
        opz = self.spawn("--harness", "pi", "--scout")
        self.assertEqual(self.profilo(opz), ("openai/gpt-6-luna", "medium"))

    def test_codex_e_altri_rifiutati(self):
        for h in ("codex", "cursor", "omp", "PI"):
            self.rifiuta(self.spawn, "--harness", h, "--semplice", contiene="ammette solo")

    def test_relaunch_pi(self):
        self.meta("t1", kind="ship", harness="pi", model="default", effort="default")
        opz = self.relaunch("--harness", "pi", "--semplice")
        self.assertEqual(self.profilo(opz), ("openai/gpt-6-luna", "medium"))


class DefaultPi(Base):
    """Decisione di Mattia del 18 novembre 2026 (consegna ccf-harness-default-pi): worker e scout Pi di default,
    un modello Anthropic nominato vuol dire Claude Code, --correzione a Claude (M-S81). Dal 19 novembre 2026 Pi solo
    con modelli OpenAI: Pi su un modello Anthropic e' rifiutato sempre, anche con motivo."""

    def harness(self, opz):
        return opz[opz.index("--harness") + 1]

    def test_senza_harness_e_pi(self):
        for tipo, atteso in (("--semplice", "openai/gpt-6-luna"), ("--complesso", "openai/gpt-6.1-sol"),
                             ("--scout", "openai/gpt-6-luna")):
            opz = self.spawn(tipo)
            self.assertEqual(self.harness(opz), "pi")
            self.assertEqual(self.profilo(opz), (atteso, "medium"))
            self.assertNotIn(tipo if tipo != "--scout" else "--x", opz)

    def test_correzione_senza_harness_e_claude(self):
        """M-S81: revisione incrociata, la correzione va a Claude opus high; Pi solo se nominato."""
        opz = self.spawn("--correzione")
        self.assertEqual((self.harness(opz), self.profilo(opz)), ("claude", ("opus", "high")))
        opz = self.spawn("--harness", "pi", "--correzione")
        self.assertEqual((self.harness(opz), self.profilo(opz)), ("pi", ("openai/gpt-6.1-sol", "medium")))

    def test_modello_anthropic_vuol_dire_claude(self):
        for m in ("opus", "sonnet", "Haiku", "claude-sonnet-5-5"):
            opz = self.spawn("--scout", "--model", m, "--dispatch-override", "chiesto da Mattia")
            self.assertEqual(self.harness(opz), "claude")
        opz = self.spawn("--complesso", "--model", "opus")
        self.assertEqual((self.harness(opz), self.profilo(opz)), ("claude", ("opus", "high")))

    def test_claude_esplicito(self):
        opz = self.spawn("--harness", "claude", "--correzione")
        self.assertEqual(self.profilo(opz), ("opus", "high"))
        self.assertEqual(self.profilo(self.spawn("--harness", "claude", "--scout")), ("sonnet", "medium"))

    ANTHROPIC = ("anthropic/claude-opus-5-5", "anthropic/claude-haiku-5-5", "Anthropic/x", "opus", "sonnet",
                 "fable", "claude-sonnet-5-5", "openrouter/claude-sonnet-5", "openrouter/Opus-5")

    def test_pi_su_anthropic_rifiutato_sempre(self):
        """19 novembre 2026: Pi solo con modelli OpenAI, anche con --dispatch-override."""
        for m in self.ANTHROPIC:
            self.rifiuta(self.spawn, "--harness", "pi", "--complesso", "--model", m, contiene="Pi non usa modelli Anthropic")
            self.rifiuta(self.spawn, "--harness", "pi", "--scout", "--model", m, contiene="Pi non usa modelli Anthropic")
            self.rifiuta(self.spawn, "--harness", "pi", "--complesso", "--model", m, "--effort", "high",
                         "--dispatch-override", "Mattia: worker Pi con Opus", contiene="--harness claude")
            self.rifiuta(self.spawn, "--harness", "pi", "--model", m, "--effort", "high",
                         "--dispatch-override", "Mattia: worker Pi con Opus", contiene="nemmeno con --dispatch-override")

    def test_pi_su_anthropic_rifiutato_al_relaunch(self):
        self.meta("t1", kind="ship", harness="pi")
        for m in ("anthropic/claude-opus-5-5", "sonnet"):
            self.rifiuta(self.relaunch, "--model", m, "--effort", "high", "--dispatch-override", "Mattia: Pi con Opus",
                         contiene="Pi non usa modelli Anthropic")
        self.meta("t2", kind="ship", harness="pi", model="anthropic/claude-opus-5-5", effort="high",
                  dispatch_override="Mattia: worker Pi con Opus")
        self.rifiuta(self.relaunch, tid="t2", contiene="Pi non usa modelli Anthropic")
        self.meta("t3", kind="ship", harness="claude", model="opus", effort="high")
        self.rifiuta(self.relaunch, "--harness", "pi", "--model", "opus", "--effort", "high",
                     "--dispatch-override", "Mattia", tid="t3", contiene="Pi non usa modelli Anthropic")

    def test_modelli_openai_e_simili_restano_a_pi(self):
        for m in ("openai/gpt-6.1-sol", "openai/gpt-6-astra"):
            opz = self.spawn("--complesso", "--model", m, "--effort", "high", "--dispatch-override", "chiesto da Mattia")
            self.assertEqual((self.harness(opz), self.profilo(opz)), ("pi", (m, "high")))

    def test_modello_con_fornitore(self):
        opz = self.spawn("--scout", "--model", "openai/gpt-6.1-sol", "--dispatch-override", "chiesto da Mattia")
        self.assertEqual(self.profilo(opz), ("openai/gpt-6.1-sol", "medium"))
        for m in ("a/b/c", "/x", "openai/", "a b"):
            self.rifiuta(self.spawn, "--scout", "--model", m, contiene="non valido")

    def test_correzione_non_per_scout(self):
        self.rifiuta(self.spawn, "--scout", "--correzione", contiene="non per uno scout")

    def test_correzione_passa_il_ruolo(self):
        """S346 (p-6f0e3c4d): --correzione arriva a fm-spawn come --role correzione; gli altri tipi no."""
        opz = self.spawn("--correzione")
        self.assertEqual(opz[-2:], ["--role", "correzione"])
        self.assertNotIn("--correzione", opz)
        for tipo in ("--complesso", "--semplice", "--scout"):
            self.assertNotIn("--role", self.spawn(tipo))

    def test_relaunch_non_passa_il_ruolo(self):
        self.meta("t3", kind="ship", harness="claude")
        self.assertNotIn("--role", self.relaunch("--correzione", tid="t3"))

    def test_relaunch_correzione(self):
        self.meta("t1", kind="ship", harness="pi")
        self.assertEqual(self.profilo(self.relaunch("--correzione")), ("openai/gpt-6.1-sol", "medium"))
        self.meta("t2", kind="ship", harness="claude")
        opz = self.relaunch("--correzione", tid="t2")
        self.assertEqual(self.profilo(opz), ("opus", "high"))
        self.assertNotIn("--correzione", opz)


class Relaunch(Base):
    def test_ship_senza_tipo_rifiuta(self):
        self.meta("t1", kind="ship", harness="claude", model="default", effort="high")
        self.rifiuta(self.relaunch, contiene="--semplice")

    def test_ship_non_eredita_il_predefinito(self):
        self.meta("t1", kind="ship", harness="claude", model="default", effort="high")
        opz = self.relaunch("--complesso")
        self.assertEqual(self.profilo(opz), ("opus", "high"))
        self.assertNotIn("--complesso", opz)
        self.assertEqual(opz[:2], ["--note", "nota"])

    def test_scout_dalla_tabella_e_motivo_fuori_dal_comando(self):
        self.meta("t1", kind="scout", harness="claude", model="default", effort="default")
        self.assertEqual(self.profilo(self.relaunch()), ("sonnet", "medium"))
        self.rifiuta(self.relaunch, "--model", "opus", contiene="--dispatch-override")
        opz = self.relaunch("--model", "opus", "--dispatch-override", "chiesto da Mattia")
        self.assertEqual(self.profilo(opz), ("opus", "medium"))
        self.assertNotIn("--dispatch-override", opz)
        self.assertNotIn("chiesto da Mattia", opz)

    def test_harness_dal_meta(self):
        self.meta("t1", kind="scout", harness="pi")
        self.assertEqual(self.profilo(self.relaunch()), ("openai/gpt-6-luna", "medium"))
        self.meta("t1", kind="ship", harness="pi")
        self.assertEqual(self.profilo(self.relaunch("--complesso")), ("openai/gpt-6.1-sol", "medium"))
        self.assertEqual(self.profilo(self.relaunch("--harness", "claude", "--semplice")), ("sonnet", "medium"))

    def test_harness_senza_regola(self):
        self.meta("t1", kind="ship", harness="codex")
        self.rifiuta(self.relaunch, "--semplice", contiene="non ha una regola")
        self.rifiuta(self.relaunch, "--model", "gpt-x", "--effort", "high", contiene="scritti a mano")
        self.assertEqual(self.profilo(self.relaunch("--model", "gpt-x", "--effort", "high",
                                                    "--dispatch-override", "chiesto da Mattia")), ("gpt-x", "high"))
        self.meta("t1", kind="scout", harness="codex")
        self.rifiuta(self.relaunch, "--model", "gpt-x", "--effort", "high", contiene="non ha una regola")

    def test_secondmate_resta_ai_suoi_pin(self):
        self.meta("t1", kind="secondmate", harness="claude")
        self.assertEqual(self.relaunch(), ["--note", "nota"])
        self.rifiuta(self.relaunch, "--model", "fable", contiene="Fable")
        self.rifiuta(self.relaunch, "--semplice", contiene="non per un task secondmate")
        self.assertEqual(self.relaunch("--model", "fable", "--dispatch-override", "Mattia: Fable"),
                         ["--note", "nota", "--model", "fable"])

    def test_fable_solo_con_motivo(self):
        self.meta("t1", kind="ship", harness="claude")
        self.rifiuta(self.relaunch, "--complesso", "--model", "fable", contiene="Fable")
        self.assertEqual(self.profilo(self.relaunch("--complesso", "--model", "fable",
                                                    "--dispatch-override", "Mattia: Fable")), ("fable", "high"))

    def test_riusa_il_meta_se_e_nella_tabella(self):
        self.meta("t1", kind="ship", harness="claude", model="opus", effort="high")
        self.assertEqual(self.profilo(self.relaunch()), ("opus", "high"))
        self.meta("t1", kind="ship", harness="claude", model="sonnet", effort="medium")
        self.assertEqual(self.profilo(self.relaunch()), ("sonnet", "medium"))
        self.meta("t1", kind="scout", harness="claude", model="sonnet", effort="high")
        self.assertEqual(self.profilo(self.relaunch()), ("sonnet", "high"))
        self.meta("t1", kind="ship", harness="pi", model="openai/gpt-6.1-sol", effort="medium")
        self.assertEqual(self.profilo(self.relaunch()), ("openai/gpt-6.1-sol", "medium"))

    def test_riusa_il_meta_fuori_tabella_solo_con_motivo(self):
        self.meta("t1", kind="ship", harness="claude", model="haiku", effort="high")
        self.rifiuta(self.relaunch, contiene="scritti a mano")
        self.assertEqual(self.profilo(self.relaunch("--dispatch-override", "chiesto da Mattia")),
                         ("haiku", "high"))
        self.meta("t1", kind="ship", harness="claude", model="haiku", effort="high",
                  dispatch_override="prova di Mattia")
        self.assertEqual(self.profilo(self.relaunch()), ("haiku", "high"))
        self.meta("t1", kind="scout", harness="claude", model="opus", effort="xhigh")
        self.rifiuta(self.relaunch, contiene="uno scout su opus")
        self.meta("t1", kind="scout", harness="claude", model="opus", effort="xhigh",
                  dispatch_override="confronto chiesto da Mattia")
        self.assertEqual(self.profilo(self.relaunch()), ("opus", "xhigh"))

    def test_fable_non_si_eredita_senza_motivo(self):
        self.meta("t1", kind="ship", harness="claude", model="fable", effort="high")
        self.rifiuta(self.relaunch, contiene="Fable")
        self.meta("t1", kind="ship", harness="claude", model="fable", effort="high",
                  dispatch_override="Mattia: usa Fable")
        self.assertEqual(self.profilo(self.relaunch()), ("fable", "high"))

    def test_senza_campi_o_con_default_vale_la_tabella(self):
        for campi in ({}, {"model": "default", "effort": "default"},
                      {"model": "opus", "effort": "default"}, {"model": "opus"}):
            self.meta("t1", kind="ship", harness="claude", **campi)
            self.rifiuta(self.relaunch, contiene="--semplice")
            self.assertEqual(self.profilo(self.relaunch("--semplice")), ("sonnet", "medium"))

    def test_flag_scritte_non_riusano_il_meta(self):
        self.meta("t1", kind="ship", harness="claude", model="haiku", effort="low")
        self.assertEqual(self.profilo(self.relaunch("--complesso")), ("opus", "high"))
        self.rifiuta(self.relaunch, "--effort", "high", contiene="--semplice")
        self.meta("t1", kind="scout", harness="claude", model="opus", effort="high",
                  dispatch_override="vecchio motivo")
        self.assertEqual(self.profilo(self.relaunch("--effort", "low")), ("sonnet", "low"))
        self.rifiuta(self.relaunch, "--model", "opus", contiene="--dispatch-override")

    def test_record_assente_rifiuta(self):
        self.rifiuta(self.relaunch, "--complesso", tid="nessuno", contiene="record del task")

    def test_altri_verbi_invariati(self):
        self.assertEqual(R.comando_control(["t1", "interrupt"])[3:], [])
        nota = os.path.join(self.tmp, "nota.txt")
        open(nota, "w").close()
        self.assertEqual(R.comando_control(["t1", "pause", "--note-file", nota])[3:], ["--note-file", nota])
        self.assertEqual(R.comando_teardown(["t1", "--no-prune"])[2:], ["--no-prune"])


class Main(Base):
    def setUp(self):
        super().setUp()
        self.env = {k: os.environ.pop(k) for k in ("FM_TASK_ID", "FM_TASK_INBOX") if k in os.environ}

    def tearDown(self):
        os.environ.update(self.env)
        super().tearDown()

    def esegui(self, *args):
        with open(os.devnull, "w") as nulla:
            vecchi = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = nulla
            try:
                return R.main(["fm-lifecycle"] + list(args))
            finally:
                sys.stdout, sys.stderr = vecchi

    def test_prova_accetta_e_rifiuta(self):
        self.assertEqual(self.esegui("--prova", "spawn", "t1", self.progetto, "--complesso"), 0)
        self.assertEqual(self.esegui("--prova", "spawn", "t1", self.progetto), 64)
        self.assertEqual(self.esegui("--prova", "spawn", "t1", self.progetto, "--scout", "--model", "opus"), 64)
        with open(os.path.join(R.LOG_DIR, "regia.log")) as f:
            righe = f.read().splitlines()
        self.assertEqual(len(righe), 2)
        self.assertTrue(all("RIFIUTATO" in r for r in righe))

    def test_verifica_segnala_la_tabella(self):
        self.assertEqual(self.esegui("verifica"), 0)
        self.dispatch(REGOLE[1:])
        self.assertEqual(self.esegui("verifica"), 1)


@unittest.skipUnless(os.path.isfile(os.path.join(R.FM, "bin", "fm-spawn.sh")), "manca ~/firstmate")
class ProgrammaVero(unittest.TestCase):
    """Il file eseguibile, con le vere cartelle di ~/firstmate, solo in --prova."""

    def lancia(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("FM_TASK_ID", "FM_TASK_INBOX")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([LIFECYCLE, "--prova"] + list(args), env=env, capture_output=True, text=True)

    def test_spawn_scout_esplicito(self):
        p = self.lancia("spawn", "prova-x", QUI, "--scout")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("'--harness', 'pi', '--model', 'openai/gpt-6-luna', '--effort', 'medium'", p.stdout)
        p = self.lancia("spawn", "prova-x", QUI, "--scout", "--harness", "claude")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("'--model', 'sonnet', '--effort', 'medium'", p.stdout)

    def test_spawn_ship_a_mano_senza_motivo_rifiutato(self):
        p = self.lancia("spawn", "t", R.FM, "--model", "haiku", "--effort", "low")
        self.assertEqual(p.returncode, 64)
        self.assertIn("--dispatch-override", p.stderr)

    def test_spawn_ship_senza_tipo_rifiutato(self):
        p = self.lancia("spawn", "prova-x", QUI, "--mode", "local-only", "--yolo", "off")
        self.assertEqual(p.returncode, 64)
        self.assertIn("--semplice", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
