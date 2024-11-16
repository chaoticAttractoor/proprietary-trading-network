import numpy as np

from tests.vali_tests.base_objects.test_base import TestBase

from vali_objects.utils.metrics import Metrics


class TestMetrics(TestBase):

    def test_return_no_positions(self):
        self.assertEqual(Metrics.base_return([]), 0.0)

    def test_negative_returns(self):
        """Test that the returns scoring function works properly for only negative returns"""
        log_returns = [-0.2, -0.1, -0.3, -0.2, -0.1, -0.3]

        base_return = Metrics.base_return(log_returns)
        self.assertLess(base_return, 0.0)

    def test_positive_returns(self):
        """Test that the returns scoring function works properly for only positive returns"""
        log_returns = [0.2, 0.1, 0.3, 0.2, 0.1, 0.3]

        base_return = Metrics.base_return(log_returns)
        self.assertGreater(base_return, 0.0)

    def test_typical_omega(self):
        """Test that the omega function works as expected for only positive returns"""
        log_returns = [0.2, -0.1, 0.3, -0.2, 0.1, 0.3]

        omega = Metrics.omega(log_returns)

        # Should always be greater or equal to 0
        self.assertGreater(omega, 0.0)

    def test_negative_omega(self):
        """Test that the omega function works as expected for only negative returns"""
        log_returns = [-0.2, -0.1, -0.3, -0.2, -0.1, -0.3]
    
        omega = Metrics.omega(log_returns)

        # Should always be less or equal to 0
        self.assertEqual(omega, 0.0)

    def test_positive_omega(self):
        """Test that the omega function works as expected for only positive returns - the default loss works"""
        log_returns = [0.2, 0.1, 0.3, 0.2, 0.1, 0.3]

        omega = Metrics.omega(log_returns)

        # Should always be greater or equal to 0, cannot be massive
        self.assertGreater(omega, 0.0)
        self.assertLess(omega, np.inf)

    def test_omega_no_returns(self):
        """Test that the omega function works as expected for no returns"""
        returns = []

        omega = Metrics.omega(returns)

        # Expected value is zero
        self.assertEqual(omega, 0.0)

    def test_positive_omega_small_loss(self):
        """Test that the omega function works as expected for only positive returns - the default loss works"""
        log_returns = [0.2, 0.1, 0.3, 0.2, 0.1, 0.3, -0.01]

        omega = Metrics.omega(log_returns)

        # Should always be greater or equal to 0, cannot be massive
        self.assertGreater(omega, 0.0)
        self.assertLess(omega, np.inf)

    def test_sharpe_positive(self):
        """Test that the sharpe function is positive when all returns are positive"""
        log_returns = [0.02, 0.01, 0.03, 0.02, 0.01, 0.03]

        sharpe = Metrics.sharpe(log_returns)

        # Should always be greater or equal to 0
        self.assertGreater(sharpe, 0.0)

    def test_sharpe_negative(self):
        """Test that the sharpe function is negative when all returns are negative"""
        log_returns = [-0.001 for _ in range(5)]

        sharpe = Metrics.sharpe(log_returns)

        # Expected value less than zero
        self.assertLess(sharpe, 0.0)
        self.assertGreater(sharpe, -10)

    def test_sharpe_no_returns(self):
        """Test that the sharpe function works as expected"""
        returns = []

        sharpe = Metrics.sharpe(returns)

        # Expected value is zero
        self.assertEqual(sharpe, 0.0)

    def test_sharpe_no_returns_no_variance(self):
        """Test that the sharpe function is negative with 0 returns"""
        log_returns = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        sharpe = Metrics.sharpe(log_returns)

        # Expected value is zero
        self.assertLess(sharpe, 0.0)

    def test_sharpe_perfect_positive_small(self):
        """Test that the sharpe function is positive for small positive returns"""
        log_returns = [0.001 for _ in range(5)]

        sharpe = Metrics.sharpe(log_returns)

        # Expected value is between zero and 10
        self.assertGreater(sharpe, 0.0)
        self.assertLess(sharpe, 10)

    def test_sharpe_perfect_positive_year(self):
        """Test that the sharpe function works for 365 days of returns"""
        log_returns = [0.05/ 365 for _ in range(365)]

        sharpe = Metrics.sharpe(log_returns)

        # Expected value is between zero and 10
        self.assertGreater(sharpe, 0.0)
        self.assertLess(sharpe, 10)

    def test_sharpe_one(self):
        """ Test that only one day of information doesn't cause errors with stddev """
        log_returns = [0.05]

        sharpe = Metrics.sharpe(log_returns)

        self.assertAlmostEqual(sharpe, 0)

    def test_swing_miners(self):
        """Test that the sharpe function works as expected"""

        total_return_1 = 0.2  # 20% total return
        n_positions_1 = 10
        per_position_return_1 = total_return_1 / n_positions_1
        m1 = [per_position_return_1 for i in range(n_positions_1)]
        
        m2 = []

        small_return_2 = 0.001
        n_positions_2 = 10
        large_return_2 = total_return_1 - (small_return_2 * (n_positions_2 - 1))

        m2 = [small_return_2 for i in range(n_positions_2 - 1)]
        m2.append(large_return_2)

        self.assertAlmostEqual(Metrics.base_return(m1), Metrics.base_return(m2), places=2)
        self.assertGreater(Metrics.sharpe(m1), Metrics.sharpe(m2))
        self.assertAlmostEqual(Metrics.omega(m2), Metrics.omega(m1))
    
    def test_sortino_general(self):
        """Test that the Sortino function returns a positive value for general returns"""
        log_returns = [0.2, 0.1, 0.3, -0.2, 0.1, -0.3]

        sortino = Metrics.sortino(log_returns)

        self.assertGreater(sortino, 0.0)


    def test_sortino_negative(self):
        """Test that the Sortino function returns a negative value for negative log returns"""
        log_returns = [-0.2, -0.1, -0.3, -0.2, -0.1, -0.3]

        sortino = Metrics.sortino(log_returns)

        # Expected value less than zero for negative returns
        self.assertLess(sortino, 0.0)
        self.assertGreater(sortino, -10)


    def test_sortino_no_returns(self):
        """Test that the Sortino function returns 0.0 when there are no returns"""
        log_returns = []

        sortino = Metrics.sortino(log_returns)

        # Expected value is zero
        self.assertEqual(sortino, 0.0)

    def test_sortino_one(self):
        """ Test that only one day of information doesn't cause errors with stddev """

        log_returns = [0.05]

        sortino = Metrics.sortino(log_returns)

        self.assertAlmostEqual(sortino, 0)

