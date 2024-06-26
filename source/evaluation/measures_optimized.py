"""
THIS FILE WAS TAKEN FROM https://github.com/BorgwardtLab/topological-autoencoders
"""


import numpy as np
import scipy
import torch
from scipy.spatial.distance import pdist, squareform
from sklearn.metrics import pairwise_distances

from torch.nn.functional import pdist as pdist_torch

from scipy.stats import spearmanr


class MeasureRegistrator():
    """Keeps track of measurements in Measure Calculator."""
    k_independent_measures = {}
    k_dependent_measures = {}

    def register(self, is_k_dependent):
        def k_dep_fn(measure):
            self.k_dependent_measures[measure.__name__] = measure
            return measure

        def k_indep_fn(measure):
            self.k_independent_measures[measure.__name__] = measure
            return measure

        if is_k_dependent:
            return k_dep_fn
        return k_indep_fn

    def get_k_independent_measures(self):
        return self.k_independent_measures

    def get_k_dependent_measures(self):
        return self.k_dependent_measures


class MeasureCalculator():
    measures = MeasureRegistrator()

    def __init__(self, X, Z, k_max):
        self.k_max = k_max
        self.pairwise_X = squareform(pdist(X))
        self.pairwise_Z = squareform(pdist(Z))
        self.X = X
        self.Z = Z

        self.neighbours_X, self.ranks_X = \
            self._neighbours_and_ranks(self.pairwise_X, k_max)
        self.neighbours_Z, self.ranks_Z = \
            self._neighbours_and_ranks(self.pairwise_Z, k_max)

    @staticmethod
    def _neighbours_and_ranks(distances, k):
        """
        Inputs: 
        - distances,        distance matrix [n times n], 
        - k,                number of nearest neighbours to consider
        Returns:
        - neighbourhood,    contains the sample indices (from 0 to n-1) of kth nearest neighbor of current sample [n times k]
        - ranks,            contains the rank of each sample to each sample [n times n], whereas entry (i,j) gives the rank that sample j has to i (the how many 'closest' neighbour j is to i) 
        """
        # Warning: this is only the ordering of neighbours that we need to
        # extract neighbourhoods below. The ranking comes later!
        indices = np.argsort(distances, axis=-1, kind='stable')

        # Extract neighbourhoods.
        neighbourhood = indices[:, 1:k + 1]

        # Convert this into ranks (finally)
        ranks = indices.argsort(axis=-1, kind='stable')

        return neighbourhood, ranks

    def get_X_neighbours_and_ranks(self, k):
        return self.neighbours_X[:, :k], self.ranks_X

    def get_Z_neighbours_and_ranks(self, k):
        return self.neighbours_Z[:, :k], self.ranks_Z

    def compute_k_independent_measures(self):
        return {key: fn(self) for key, fn in
                self.measures.get_k_independent_measures().items()}

    def compute_k_dependent_measures(self, k):
        return {key: fn(self, k) for key, fn in
                self.measures.get_k_dependent_measures().items()}

    def compute_measures_for_ks(self, ks):
        return {
            key: np.array([fn(self, k) for k in ks])
            for key, fn in self.measures.get_k_dependent_measures().items()
        }

    @measures.register(False)
    def stress(self):
        sum_of_squared_differences = \
            np.square(self.pairwise_X - self.pairwise_Z).sum()
        sum_of_squares = np.square(self.pairwise_Z).sum()

        return np.sqrt(sum_of_squared_differences / sum_of_squares)

    @measures.register(False)
    def rmse(self):
        """
        rmse of between the distance matrix in input- and latent-space
        """
        n = self.pairwise_X.shape[0]
        sum_of_squared_differences = np.square(
            self.pairwise_X - self.pairwise_Z).sum()
        return np.sqrt(sum_of_squared_differences / n ** 2)

    @staticmethod
    def _trustworthiness(X_neighbourhood, X_ranks, Z_neighbourhood,
                         Z_ranks, n, k):
        '''
        Calculates the trustworthiness measure between the data space `X`
        and the latent space `Z`, given a neighbourhood parameter `k` for
        defining the extent of neighbourhoods.
        '''

        result = 0.0

        # Calculate number of neighbours that are in the $k$-neighbourhood
        # of the latent space but not in the $k$-neighbourhood of the data
        # space.
        for row in range(X_ranks.shape[0]):
            missing_neighbours = np.setdiff1d(
                Z_neighbourhood[row],
                X_neighbourhood[row]
            )

            for neighbour in missing_neighbours:
                result += (X_ranks[row, neighbour] - k)

        return 1 - 2 / (n * k * (2 * n - 3 * k - 1)) * result

    @measures.register(True)
    def trustworthiness(self, k):
        """
        Measures the preservation of k nearest neighbor graph
        """
        X_neighbourhood, X_ranks = self.get_X_neighbours_and_ranks(k)
        Z_neighbourhood, Z_ranks = self.get_Z_neighbours_and_ranks(k)
        n = self.pairwise_X.shape[0]
        return self._trustworthiness(X_neighbourhood, X_ranks, Z_neighbourhood,
                                     Z_ranks, n, k)

    @measures.register(True)
    def continuity(self, k):
        '''
        Calculates the continuity measure between the data space `X` and the
        latent space `Z`, given a neighbourhood parameter `k` for setting up
        the extent of neighbourhoods.

        This is just the 'flipped' variant of the 'trustworthiness' measure.
        '''

        X_neighbourhood, X_ranks = self.get_X_neighbours_and_ranks(k)
        Z_neighbourhood, Z_ranks = self.get_Z_neighbours_and_ranks(k)
        n = self.pairwise_X.shape[0]
        # Notice that the parameters have to be flipped here.
        return self._trustworthiness(Z_neighbourhood, Z_ranks, X_neighbourhood,
                                     X_ranks, n, k)

    @measures.register(True)
    def neighbourhood_loss(self, k):
        '''
        Calculates the neighbourhood loss quality measure between the data
        space `X` and the latent space `Z` for some neighbourhood size $k$
        that has to be pre-defined.
        '''

        X_neighbourhood, _ = self.get_X_neighbours_and_ranks(k)
        Z_neighbourhood, _ = self.get_Z_neighbours_and_ranks(k)

        result = 0.0
        n = self.pairwise_X.shape[0]

        for row in range(n):
            shared_neighbours = np.intersect1d(
                X_neighbourhood[row],
                Z_neighbourhood[row],
                assume_unique=True
            )

            result += len(shared_neighbours) / k

        return 1.0 - result / n

    @measures.register(True)
    def rank_correlation(self, k):
        '''
        Calculates the spearman rank correlation of the data
        space `X` with respect to the latent space `Z`, subject to its $k$
        nearest neighbours.
        '''

        X_neighbourhood, X_ranks = self.get_X_neighbours_and_ranks(k)
        Z_neighbourhood, Z_ranks = self.get_Z_neighbours_and_ranks(k)

        n = self.pairwise_X.shape[0]
        # we gather
        gathered_ranks_x = []
        gathered_ranks_z = []
        for row in range(n):
            # we go from X to Z here:
            for neighbour in X_neighbourhood[row]:
                rx = X_ranks[row, neighbour]
                rz = Z_ranks[row, neighbour]
                gathered_ranks_x.append(rx)
                gathered_ranks_z.append(rz)
        rs_x = np.array(gathered_ranks_x)
        rs_z = np.array(gathered_ranks_z)
        coeff, _ = spearmanr(rs_x, rs_z)

        ##use only off-diagonal (non-trivial) ranks:
        # inds = ~np.eye(X_ranks.shape[0],dtype=bool)
        # coeff, pval = spearmanr(X_ranks[inds], Z_ranks[inds])
        return coeff

    def kNN_graph(self, x, k):
        """  Implementation of a k nearest neighbor graph
        :param x: array containing the dataset
        :param k: number of neartest neighbors
        :param metric: Metric used for distances of x, must be "euclidean" or "cosine".
        :return: array of shape (len(x), k) containing the indices of the k nearest neighbors of each datapoint     """

        dists = torch.cdist(x, x)

        # knn_idx = dists.argKmin(K=k + 1, dim=0)[:, 1:]  # use k+1 neighbours and omit first, which is just the point itself
        topk = torch.topk(dists, dim=0, k=k + 1, largest=False)
        knn_idx = topk.indices[1:, :].T

        return knn_idx

    @measures.register(True)
    def knn_recall(self, k):
        """     Computes the accuracy of k nearest neighbors between x and y.
        :param x: array of positions for first dataset
        :param y: array of positions for second dataset
        :param k: number of nearest neighbors considered
        :param metric: Metric used for distances of x, must be a metric available for sklearn.metrics.pairwise_distances
        :return: Share of x's k nearest neighbors that are also y's k nearest neighbors     """

        metric = "euclidean"

        x = torch.from_numpy(self.Z)
        y = torch.from_numpy(self.X)

        x_kNN = scipy.sparse.coo_matrix((np.ones(len(x) * k), (
            np.repeat(np.arange(x.shape[0]), k), self.kNN_graph(x, k).numpy().flatten())),
                                        shape=(len(x), len(x)))
        y_kNN = scipy.sparse.coo_matrix(
            (np.ones(len(y) * k), (np.repeat(np.arange(y.shape[0]), k), self.kNN_graph(y, k).numpy().flatten())),
            shape=(len(y), len(y)))
        overlap = x_kNN.multiply(y_kNN)
        matched_kNNs = overlap.sum()

        return matched_kNNs / (len(x) * k)

    @measures.register(False)
    def spearman_metric(self):
        """
        Computes correlation between pairwise distances among the x's and among the y's
        :param x: array of positions for x
        :param y: array of positions for y
        :param sample_size: number of points to subsample from x and y for pairwise distance computation
        :param seed: random seed
        :param metric: Metric used for distances of x, must be a metric available for sklearn.metrics.pairwise_distances
        :return: tuple of Pearson and Spearman correlation coefficient
        """

        seed = 42
        sample_size = 1000
        metric = "euclidean"

        x = self.X
        y = self.Z

        np.random.seed(seed)
        sample_idx = np.random.randint(len(x), size=sample_size)
        x_sample = x[sample_idx]
        y_sample = y[sample_idx]

        x_dists = pairwise_distances(x_sample, metric=metric).flatten()
        y_dists = pairwise_distances(y_sample, metric="euclidean").flatten()

        spear_r, _ = spearmanr(x_dists, y_dists)

        return spear_r

    @measures.register(True)
    def mrre(self, k):
        '''
        Calculates the mean relative rank error quality metric of the data
        space `X` with respect to the latent space `Z`, subject to its $k$
        nearest neighbours.
        '''

        X_neighbourhood, X_ranks = self.get_X_neighbours_and_ranks(k)
        Z_neighbourhood, Z_ranks = self.get_Z_neighbours_and_ranks(k)

        n = self.pairwise_X.shape[0]

        # First component goes from the latent space to the data space, i.e.
        # the relative quality of neighbours in `Z`.

        mrre_ZX = 0.0
        for row in range(n):
            for neighbour in Z_neighbourhood[row]:
                rx = X_ranks[row, neighbour]
                rz = Z_ranks[row, neighbour]

                mrre_ZX += abs(rx - rz) / rz

        # Second component goes from the data space to the latent space,
        # i.e. the relative quality of neighbours in `X`.

        mrre_XZ = 0.0
        for row in range(n):
            # Note that this uses a different neighbourhood definition!
            for neighbour in X_neighbourhood[row]:
                rx = X_ranks[row, neighbour]
                rz = Z_ranks[row, neighbour]

                # Note that this uses a different normalisation factor
                mrre_XZ += abs(rx - rz) / rx

        # Normalisation constant
        C = n * sum([abs(2 * j - n - 1) / j for j in range(1, k + 1)])
        return mrre_ZX / C, mrre_XZ / C

    @measures.register(False)
    def density_global(self, sigma=0.1):
        X = self.pairwise_X
        X = X / X.max()
        Z = self.pairwise_Z
        Z = Z / Z.max()

        density_x = np.sum(np.exp(-(X ** 2) / sigma), axis=-1)
        density_x /= density_x.sum(axis=-1)

        density_z = np.sum(np.exp(-(Z ** 2) / sigma), axis=-1)
        density_z /= density_z.sum(axis=-1)

        return np.abs(density_x - density_z).sum()

    # @measures.register(False)
    def density_kl_global(self, sigma=0.1):
        X = self.pairwise_X
        X = X / X.max()
        Z = self.pairwise_Z
        Z = Z / Z.max()

        density_x = np.sum(np.exp(-(X ** 2) / sigma), axis=-1)

        density_x /= density_x.sum(axis=-1)

        density_z = np.sum(np.exp(-(Z ** 2) / sigma), axis=-1)
        density_z /= density_z.sum(axis=-1)

        return (density_x * (np.log(density_x) - np.log(density_z))).sum()

    @measures.register(False)
    def density_kl_global_100(self):
        return self.density_kl_global(100.)

    @measures.register(False)
    def density_kl_global_01(self):
        return self.density_kl_global(0.1)
