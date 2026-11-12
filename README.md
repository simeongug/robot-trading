# Robot de trading expérimental (argent fictif)

Un robot qui décide chaque jour quoi acheter ou vendre parmi une poignée d'ETF
américains, et qui exécute ses ordres sur un **compte de démonstration Alpaca**
(100 000 $ fictifs). But : savoir, chiffres à l'appui, si une stratégie
automatique fait mieux que d'acheter le S&P 500 et de ne plus y toucher.

> Expérience, pas conseil en investissement. Le code est verrouillé sur le
> compte de démonstration : aucun argent réel n'est engagé.

## Où regarder

| Fichier | Contenu |
|---|---|
| [REPORT.md](REPORT.md) | Situation du robot, mise à jour chaque jour de bourse |
| [reports/backtest.md](reports/backtest.md) | Résultats des stratégies sur plus de 20 ans |
| [journal/](journal/) | Historique de la valeur du compte et de chaque ordre |
| [config.json](config.json) | Réglages : stratégie active, marges de sécurité |

## Comment ça tourne

Tout s'exécute gratuitement sur GitHub Actions (onglet **Actions** du repo) :

- **Robot quotidien** : du lundi au vendredi vers 15h45 (heure de Paris).
  Il lit les clôtures de la veille, calcule la cible, passe les ordres et met à
  jour `REPORT.md`. Bouton « Run workflow » pour le lancer à la main, avec une
  case « Simulation seulement ».
- **Backtest** : à la demande, à chaque changement de stratégie, et le 1er de
  chaque mois.
- **Tests** : à chaque modification du code.

## Mise en route (une seule fois)

1. Compte Alpaca en mode **Paper**, puis une clé d'API.
2. Dans ce repo : Settings → Secrets and variables → Actions, créer
   `ALPACA_API_KEY` et `ALPACA_SECRET_KEY`.
3. Onglet Actions → « Backtest des stratégies » → Run workflow.
4. Onglet Actions → « Robot quotidien » → Run workflow, case simulation cochée,
   pour vérifier que tout est branché.

## Les stratégies

Des méthodes publiques et connues, choisies avant de regarder les résultats.

| Nom | Idée |
|---|---|
| `buy_hold` | Référence : 100 % S&P 500, on ne touche à rien |
| `trend_sma200` | S&P 500 tant qu'il est au-dessus de sa moyenne 200 jours, sinon obligations |
| `dual_momentum` | Chaque mois : le meilleur des marchés US ou internationaux, sinon obligations |
| `rotation_momentum` | Chaque mois : les 3 ETF qui montent le plus (actions, obligations, or) |
| `rsi2_reversion` | Achète les petits replis du S&P 500 et revend au rebond |

Pour changer de stratégie, modifier `"strategy"` dans `config.json`.
Pour tout arrêter : `"enabled": false`.

## Garde-fous

- Adresse du compte réel absente du code ; le client refuse toute autre adresse.
- Aucun levier, aucune vente à découvert, uniquement des ETF très liquides.
- Les ordres ne partent que si le marché est ouvert et si les données ont moins de 5 jours.
- Ventes avant achats ; 2 % de cash gardé ; petits ajustements ignorés.
- Nombre d'ordres limité par exécution.

## Limites à garder en tête

- Un backtest réussi ne garantit rien : ces stratégies sont connues de tous.
- Les cours viennent de Yahoo Finance (gratuit, non officiel, parfois en retard).
- Le compte de démonstration remplit les ordres de façon idéale ; le réel est
  un peu moins favorable.

## En local

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m bot.backtest
DRY_RUN=1 ALPACA_API_KEY=... ALPACA_SECRET_KEY=... python -m bot.live
```
