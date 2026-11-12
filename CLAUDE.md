# Consignes pour Claude

- Ce robot reste sur le compte de démonstration Alpaca. Ne jamais ajouter l'adresse du
  compte réel, ni de levier, ni de vente à découvert, sauf demande explicite et écrite
  du propriétaire du repo dans la conversation.
- Pas de clé d'API dans le code ou les fichiers : uniquement les secrets GitHub.
- Une stratégie ne passe dans `config.json` qu'après un backtest comparé à `buy_hold`,
  avec la période hors échantillon (depuis 2015) mise en avant.
- Une stratégie reçoit les clôtures et renvoie des poids ; le poids du jour t n'utilise
  que des données connues à la clôture de t. Le test `test_no_lookahead` le vérifie.
- Lancer `python -m unittest discover -s tests` avant chaque commit.
- Le propriétaire ne lit pas le code : expliquer les changements en français simple.
