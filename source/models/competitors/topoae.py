import numpy as np
import torch
import torch.nn as nn

from models.competitors.topology import (
    PersistentHomologyCalculation,
)  # AlephPersistenHomologyCalculation, \

from models.ae import AE


class TopologicallyRegularizedAutoencoder(AE):
    """Topologically regularized autoencoder, from the Topological Autoenocoder paper"""

    def __init__(
        self,
        encoder,
        decoder,
        toposig_kwargs=None,
    ):
        """Topologically Regularized Autoencoder.

        Args:
            lam: Regularization strength
            ae_kwargs: Kewords to pass to `ConvolutionalAutoencoder` class
            toposig_kwargs: Keywords to pass to `TopologicalSignature` class
        """
        super().__init__(encoder, decoder)
        self.lam = 0.5
        toposig_kwargs = toposig_kwargs if toposig_kwargs else {}
        self.topo_sig = TopologicalSignatureDistance(**toposig_kwargs)
        self.latent_norm = torch.nn.Parameter(data=torch.ones(1), requires_grad=True)

    @staticmethod
    def _compute_distance_matrix(x, p=2):
        x_flat = x.view(x.size(0), -1)
        distances = torch.norm(x_flat[:, None] - x_flat, dim=2, p=p)
        return distances

    def train_step(self, x, optimizer, **kwargs):
        optimizer.zero_grad()
        z = self.encode(x)
        recon = self.decode(z)
        mse = ((recon - x) ** 2).view(len(x), -1).mean(dim=1).mean()

        x_distances = self._compute_distance_matrix(x)

        dimensions = x.size()
        if len(dimensions) == 4:
            # If we have an image dataset, normalize using theoretical maximum
            batch_size, ch, b, w = dimensions
            # Compute the maximum distance we could get in the data space (this
            # is only valid for images wich are normalized between -1 and 1)
            max_distance = (2**2 * ch * b * w) ** 0.5
            x_distances = x_distances / max_distance
        else:
            # Else just take the max distance we got in the batch
            x_distances = x_distances / x_distances.max()

        latent_distances = self._compute_distance_matrix(z)
        latent_distances = latent_distances / self.latent_norm

        topo_error, _ = self.topo_sig(x_distances, latent_distances)

        # normalize topo_error according to batch_size
        batch_size = dimensions[0]
        topo_loss = topo_error / float(batch_size)

        loss = mse + self.lam * topo_loss

        loss.backward()
        optimizer.step()
        return {"loss": loss.item(), "mse": mse.item(), "reg": topo_loss.item()}


class TopologicalSignatureDistance(nn.Module):
    """Topological signature."""

    def __init__(self, sort_selected=False, use_cycles=False, match_edges=None):
        """Topological signature computation.

        Args:
            p: Order of norm used for distance computation
            use_cycles: Flag to indicate whether cycles should be used
                or not.
        """
        super().__init__()
        self.use_cycles = use_cycles

        self.match_edges = match_edges

        # if use_cycles:
        #     use_aleph = True
        # else:
        #     if not sort_selected and match_edges is None:
        #         use_aleph = True
        #     else:
        #         use_aleph = False

        # if use_aleph:
        #     print('Using aleph to compute signatures')
        ##self.signature_calculator = AlephPersistenHomologyCalculation(
        ##    compute_cycles=use_cycles, sort_selected=sort_selected)
        # else:
        print("Using python to compute signatures")
        self.signature_calculator = PersistentHomologyCalculation()

    def _get_pairings(self, distances):
        pairs_0, pairs_1 = self.signature_calculator(distances.detach().cpu().numpy())

        return pairs_0, pairs_1

    def _select_distances_from_pairs(self, distance_matrix, pairs):
        # Split 0th order and 1st order features (edges and cycles)
        pairs_0, pairs_1 = pairs
        selected_distances = distance_matrix[(pairs_0[:, 0], pairs_0[:, 1])]

        if self.use_cycles:
            edges_1 = distance_matrix[(pairs_1[:, 0], pairs_1[:, 1])]
            edges_2 = distance_matrix[(pairs_1[:, 2], pairs_1[:, 3])]
            edge_differences = edges_2 - edges_1

            selected_distances = torch.cat((selected_distances, edge_differences))

        return selected_distances

    @staticmethod
    def sig_error(signature1, signature2):
        """Compute distance between two topological signatures."""
        return ((signature1 - signature2) ** 2).sum(dim=-1)

    @staticmethod
    def _count_matching_pairs(pairs1, pairs2):
        def to_set(array):
            return set(tuple(elements) for elements in array)

        return float(len(to_set(pairs1).intersection(to_set(pairs2))))

    @staticmethod
    def _get_nonzero_cycles(pairs):
        all_indices_equal = np.sum(pairs[:, [0]] == pairs[:, 1:], axis=-1) == 3
        return np.sum(np.logical_not(all_indices_equal))

    # pylint: disable=W0221
    def forward(self, distances1, distances2):
        """Return topological distance of two pairwise distance matrices.

        Args:
            distances1: Distance matrix in space 1
            distances2: Distance matrix in space 2

        Returns:
            distance, dict(additional outputs)
        """
        pairs1 = self._get_pairings(distances1)
        pairs2 = self._get_pairings(distances2)

        distance_components = {
            "metrics.matched_pairs_0D": self._count_matching_pairs(pairs1[0], pairs2[0])
        }
        # Also count matched cycles if present
        if self.use_cycles:
            distance_components[
                "metrics.matched_pairs_1D"
            ] = self._count_matching_pairs(pairs1[1], pairs2[1])
            nonzero_cycles_1 = self._get_nonzero_cycles(pairs1[1])
            nonzero_cycles_2 = self._get_nonzero_cycles(pairs2[1])
            distance_components["metrics.non_zero_cycles_1"] = nonzero_cycles_1
            distance_components["metrics.non_zero_cycles_2"] = nonzero_cycles_2

        if self.match_edges is None:
            sig1 = self._select_distances_from_pairs(distances1, pairs1)
            sig2 = self._select_distances_from_pairs(distances2, pairs2)
            distance = self.sig_error(sig1, sig2)

        elif self.match_edges == "symmetric":
            sig1 = self._select_distances_from_pairs(distances1, pairs1)
            sig2 = self._select_distances_from_pairs(distances2, pairs2)
            # Selected pairs of 1 on distances of 2 and vice versa
            sig1_2 = self._select_distances_from_pairs(distances2, pairs1)
            sig2_1 = self._select_distances_from_pairs(distances1, pairs2)

            distance1_2 = self.sig_error(sig1, sig1_2)
            distance2_1 = self.sig_error(sig2, sig2_1)

            distance_components["metrics.distance1-2"] = distance1_2
            distance_components["metrics.distance2-1"] = distance2_1

            distance = distance1_2 + distance2_1

        elif self.match_edges == "random":
            # Create random selection in oder to verify if what we are seeing
            # is the topological constraint or an implicit latent space prior
            # for compactness
            n_instances = len(pairs1[0])
            pairs1 = torch.cat(
                [
                    torch.randperm(n_instances)[:, None],
                    torch.randperm(n_instances)[:, None],
                ],
                dim=1,
            )
            pairs2 = torch.cat(
                [
                    torch.randperm(n_instances)[:, None],
                    torch.randperm(n_instances)[:, None],
                ],
                dim=1,
            )

            sig1_1 = self._select_distances_from_pairs(distances1, (pairs1, None))
            sig1_2 = self._select_distances_from_pairs(distances2, (pairs1, None))

            sig2_2 = self._select_distances_from_pairs(distances2, (pairs2, None))
            sig2_1 = self._select_distances_from_pairs(distances1, (pairs2, None))

            distance1_2 = self.sig_error(sig1_1, sig1_2)
            distance2_1 = self.sig_error(sig2_1, sig2_2)
            distance_components["metrics.distance1-2"] = distance1_2
            distance_components["metrics.distance2-1"] = distance2_1

            distance = distance1_2 + distance2_1

        return distance, distance_components
