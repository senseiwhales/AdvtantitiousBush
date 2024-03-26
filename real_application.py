import numpy as np
import pandas as pd
import os
import logging
import alpaca_trade_api as tradeapi

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler('trades.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

class DecisionTree:
    def __init__(self, max_depth=None, max_features=None):
        self.max_depth = max_depth
        self.max_features = max_features
        self.tree = None

    def fit(self, X, y):
        self.tree = self._build_tree(X, y, depth=0)

    def _build_tree(self, X, y, depth):
        n_samples, n_features = X.shape
        n_labels = len(np.unique(y))

        if depth == self.max_depth or n_labels == 1:
            leaf_value = self._compute_leaf_value(y)
            return {'leaf': True, 'value': leaf_value}

        feature_indices = np.random.choice(n_features, size=self.max_features, replace=False)
        best_feature, best_threshold = self._find_best_split(X, y, feature_indices)

        if best_feature is None:
            leaf_value = self._compute_leaf_value(y)
            return {'leaf': True, 'value': leaf_value}

        left_indices = X[:, best_feature] < best_threshold
        right_indices = ~left_indices

        left_subtree = self._build_tree(X[left_indices], y[left_indices], depth + 1)
        right_subtree = self._build_tree(X[right_indices], y[right_indices], depth + 1)

        return {'leaf': False, 'feature': best_feature, 'threshold': best_threshold,
                'left': left_subtree, 'right': right_subtree}

    def _find_best_split(self, X, y, feature_indices):
        best_gain = -float('inf')
        best_feature = None
        best_threshold = None

        for feature_index in feature_indices:
            thresholds = np.unique(X[:, feature_index])

            for threshold in thresholds:
                left_indices = X[:, feature_index] < threshold
                right_indices = ~left_indices

                if np.sum(left_indices) == 0 or np.sum(right_indices) == 0:
                    continue

                gain = self._compute_gain(y, y[left_indices], y[right_indices])
                if gain > best_gain:
                    best_gain = gain
                    best_feature = feature_index
                    best_threshold = threshold

        return best_feature, best_threshold

    def _compute_gain(self, y, left_y, right_y):
        n = len(y)
        left_n = len(left_y)
        right_n = len(right_y)

        entropy_parent = self._compute_entropy(y)
        entropy_children = (left_n / n) * self._compute_entropy(left_y) + (right_n / n) * self._compute_entropy(right_y)

        return entropy_parent - entropy_children

    def _compute_entropy(self, y):
        _, counts = np.unique(y, return_counts=True)
        probabilities = counts / len(y)
        entropy = -np.sum(probabilities * np.log2(probabilities + 1e-10))
        return entropy

    def _compute_leaf_value(self, y):
        return np.mean(y)

    def predict(self, X):
        return np.array([self._traverse_tree(x, self.tree) for x in X])

    def _traverse_tree(self, x, node):
        if node['leaf']:
            return node['value']

        if x[node['feature']] < node['threshold']:
            return self._traverse_tree(x, node['left'])
        else:
            return self._traverse_tree(x, node['right'])


class MLTrader:
    def __init__(self, symbol: str = "MAT", starting_cash: float = 10000):
        self.symbol = symbol
        self.total_cash = starting_cash
        self.model = DecisionTree(max_depth=10, max_features=3)
        self.alpaca = tradeapi.REST('YOUR_API_KEY', 'YOUR_SECRET_KEY', base_url='https://paper-api.alpaca.markets')
        self.trades = []

    def on_trading_iteration(self):
        current_dir = os.path.dirname(__file__)
        data = self.load_stock_data(os.path.join(current_dir, f'{self.symbol}.csv'))
        if data is None:
            logger.error("Failed to load stock data.")
            return
        logger.info("Stock data loaded successfully.")
        
        X = data[['o', 'h', 'l', 'c', 'v']].values
        y = data['c'].values

        self.model.fit(X, y)
        predictions = self.model.predict(X)
        current_prices = data['c'].values
        next_day_prices = np.roll(current_prices, -1)
        next_day_prices[-1] = current_prices[-1]
        self.make_trades(predictions, current_prices, next_day_prices)

    def make_trades(self, predictions, current_prices, next_day_prices):
        for i in range(len(predictions)):
            if predictions[i] > current_prices[i]:  # Predicted price is higher, buy
                if self.total_cash > 0:  # Ensure enough cash to buy
                    qty_to_buy = int(self.total_cash / current_prices[i])  # Calculate quantity to buy
                    if qty_to_buy > 0:
                        self.alpaca.submit_order(self.symbol, qty_to_buy, 'buy', 'market', 'gtc')
                        self.total_cash -= qty_to_buy * current_prices[i]
                        logger.info(f"Bought {qty_to_buy} shares of {self.symbol} at {current_prices[i]}")
            elif predictions[i] < current_prices[i]:  # Predicted price is lower, sell
                if self.total_cash > 0:  # Ensure holding some stocks to sell
                    positions = self.alpaca.list_positions()
                    for position in positions:
                        if position.symbol == self.symbol:
                            self.alpaca.submit_order(self.symbol, position.qty, 'sell', 'market', 'gtc')
                            self.total_cash += position.qty * current_prices[i]
                            logger.info(f"Sold {position.qty} shares of {self.symbol} at {current_prices[i]}")

    def load_stock_data(self, file_path):
        try:
            # Read the CSV file
            data = pd.read_csv(file_path, index_col='t')

            # Check if the required columns are present
            required_columns = ['o', 'h', 'l', 'c', 'v']  # Modify the required columns accordingly
            if not set(required_columns).issubset(data.columns):
                missing_columns = set(required_columns) - set(data.columns)
                logger.error(f"Missing required columns: {missing_columns}")
                return None

            return data
        except Exception as e:
            logger.error(f"Error loading data from file {file_path}: {e}")
            return None


if __name__ == "__main__":
    starting_cash = 10000  # Set your desired starting cash here
    strategy = MLTrader(symbol='MAT2', starting_cash=starting_cash)
    
    # Define the number of trading iterations (days) you want to simulate
    num_trading_days = 200  # Change this to the desired number of trading days
    
    for day in range(1, num_trading_days + 1):
        strategy.on_trading_iteration()
        print(f"Profit after Day {day}: ${strategy.total_cash - starting_cash:.2f}")
    
    print("Total cash:", strategy.total_cash)