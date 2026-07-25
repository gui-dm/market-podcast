import unittest
from datetime import datetime

from zoneinfo import ZoneInfo

from editorial_validation import validate_episode

TZ = ZoneInfo("America/Sao_Paulo")


DISCLAIMER = (
    "Este conteúdo tem caráter exclusivamente informativo e não constitui "
    "recomendação de investimento."
)


def valid_script(greeting="Bom dia."):
    body = " ".join(["informação confirmada para o mercado brasileiro"] * 62)
    return f"{greeting} {body} {DISCLAIMER}"


def valid_audit():
    return [{
        "tipo": "cotacao",
        "item": "Brent futuro",
        "valor_ou_fato": "US$ 95",
        "data": "24/07/2026",
        "horario": "07:40",
        "instrumento": "BZ=F, vencimento de referência",
        "fonte": "Yahoo Finance",
        "url": "https://finance.yahoo.com/quote/BZ=F",
    }]


class EpisodeValidationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 24, 8, 0, tzinfo=TZ)

    def test_accepts_complete_opening(self):
        validate_episode("abertura", valid_script(), valid_audit(), self.now)

    def test_blocks_missing_audit(self):
        with self.assertRaisesRegex(ValueError, "ficha de auditoria ausente"):
            validate_episode("abertura", valid_script(), [], self.now)

    def test_blocks_quote_without_instrument(self):
        audit = valid_audit()
        audit[0]["instrumento"] = ""
        with self.assertRaisesRegex(ValueError, "sem instrumento"):
            validate_episode("abertura", valid_script(), audit, self.now)

    def test_blocks_short_script(self):
        with self.assertRaisesRegex(ValueError, "roteiro curto"):
            validate_episode("abertura", f"Bom dia. Mercado. {DISCLAIMER}", valid_audit(), self.now)

    def test_blocks_wrong_closing_greeting(self):
        with self.assertRaisesRegex(ValueError, "saudação inválida"):
            validate_episode("fechamento", valid_script(), valid_audit(), self.now)


if __name__ == "__main__":
    unittest.main()
