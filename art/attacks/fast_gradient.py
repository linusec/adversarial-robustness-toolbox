from __future__ import absolute_import, division, print_function, unicode_literals

import numpy as np

from art.attacks.attack import Attack
from art.utils import get_labels_np_array


class FastGradientMethod(Attack):
    """
    This attack was originally implemented by Goodfellow et al. (2015) with the infinity norm (and is known as the "Fast
    Gradient Sign Method"). This implementation extends the attack to other norms, and is therefore called the Fast
    Gradient Method. Paper link: https://arxiv.org/abs/1412.6572
    """
    attack_params = Attack.attack_params + ['norm', 'eps', 'targeted']

    def __init__(self, classifier, norm=np.inf, eps=.3, targeted=False):
        """
        Create a :class:`FastGradientMethod` instance.

        :param classifier: A trained model.
        :type classifier: :class:`Classifier`
        :param norm: Order of the norm. Possible values: np.inf, 1 or 2.
        :type norm: `int`
        :param eps: Attack step size (input variation)
        :type eps: `float`
        :param targeted: Should the attack target one specific class
        :type targeted: `bool`
        """
        super(FastGradientMethod, self).__init__(classifier)

        self.norm = norm
        self.eps = eps
        self.targeted = targeted

    def _minimal_perturbation(self, x, y, eps_step=0.1, eps_max=1., **kwargs):
        """Iteratively compute the minimal perturbation necessary to make the class prediction change. Stop when the
        first adversarial example was found.

        :param x: An array with the original inputs
        :type x: `np.ndarray`
        :param y:
        :type y:
        :param eps_step: The increase in the perturbation for each iteration
        :type eps_step: `float`
        :param eps_max: The maximum accepted perturbation
        :type eps_max: `float`
        :return: An array holding the adversarial examples
        :rtype: `np.ndarray`
        """
        self.set_params(**kwargs)
        adv_x = x.copy()

        # Compute perturbation with implicit batching
        batch_size = 128
        for batch_id in range(adv_x.shape[0] // batch_size + 1):
            batch_index_1, batch_index_2 = batch_id * batch_size, (batch_id + 1) * batch_size
            batch = adv_x[batch_index_1:batch_index_2]
            batch_labels = y[batch_index_1:batch_index_2]

            # Get perturbation
            perturbation = self._compute_perturbation(batch, batch_labels)

            # Get current predictions
            active_indices = np.arange(len(batch))
            current_eps = eps_step
            
            while len(active_indices) != 0 and current_eps <= eps_max:
                # Adversarial crafting
                current_x = self._apply_perturbation(x, perturbation, current_eps)

                # Update
                batch[active_indices] = current_x[active_indices]
                adv_preds = self.classifier.predict(batch)
                active_indices = np.where(np.argmax(batch_labels, axis=1) == np.argmax(adv_preds, axis=1))[0]
                current_eps += eps_step
            
            adv_x[batch_index_1:batch_index_2] = batch

        return adv_x

    def generate(self, x, **kwargs):
        """Generate adversarial samples and return them in an array.

        :param x: An array with the original inputs.
        :type x: `np.ndarray`
        :param eps: Attack step size (input variation)
        :type eps: `float`
        :param norm: Order of the norm (mimics Numpy). Possible values: np.inf, 1 or 2.
        :type norm: `int`
        :param y: The labels for the data `x`. Only provide this parameter if you'd like to use true
                  labels when crafting adversarial samples. Otherwise, model predictions are used as labels to avoid the
                  "label leaking" effect (explained in this paper: https://arxiv.org/abs/1611.01236). Default is `None`.
                  Labels should be one-hot-encoded.
        :type y: `np.ndarray`
        :param minimal: `True` if only the minimal perturbation should be computed. In that case, use `eps_step` for the
                        step size and `eps_max` for the total allowed perturbation.
        :type minimal: `bool`
        :return: An array holding the adversarial examples.
        :rtype: `np.ndarray`
        """
        self.set_params(**kwargs)
        params_cpy = dict(kwargs)

        if 'y' not in params_cpy or params_cpy[str('y')] is None:
            # Throw error if attack is targeted, but no targets are provided
            if self.targeted:
                raise ValueError('Target labels `y` need to be provided for a targeted attack.')

            # Use model predictions as correct outputs
            y = get_labels_np_array(self.classifier.predict(x))
        else:
            y = params_cpy.pop(str('y'))
        y = y / np.sum(y, axis=1, keepdims=True)

        # Return adversarial examples computed with minimal perturbation if option is active
        if 'minimal' in params_cpy and params_cpy[str('minimal')]:
            return self._minimal_perturbation(x, y, **params_cpy)

        return self._compute(x, y, self.eps)

    def set_params(self, **kwargs):
        """
        Take in a dictionary of parameters and applies attack-specific checks before saving them as attributes.

        :param norm: Order of the norm. Possible values: np.inf, 1 or 2.
        :type norm: `int` or `float`
        :param eps: Attack step size (input variation)
        :type eps: `float`
        :param targeted: Should the attack target one specific class
        :type targeted: `bool`
        """
        # Save attack-specific parameters
        super(FastGradientMethod, self).set_params(**kwargs)

        # Check if order of the norm is acceptable given current implementation
        if self.norm not in [np.inf, int(1), int(2)]:
            raise ValueError('Norm order must be either `np.inf`, 1, or 2.')

        if self.eps <= 0:
            raise ValueError('The perturbation size `eps` has to be positive.')
        return True

    def _compute_perturbation(self, batch, batch_labels):
        # Pick a small scalar to avoid division by 0
        tol = 10e-8
        
        # Get gradient wrt loss; invert it if attack is targeted
        grad = self.classifier.loss_gradient(batch, batch_labels) * (1 - 2 * int(self.targeted))
       
        # Apply norm bound
        if self.norm == np.inf:
            grad = np.sign(grad)
        elif self.norm == 1:
            ind = tuple(range(1, len(batch.shape)))
            grad = grad / (np.sum(np.abs(grad), axis=ind, keepdims=True) + tol)
        elif self.norm == 2:
            ind = tuple(range(1, len(batch.shape)))
            grad = grad / (np.sqrt(np.sum(np.square(grad), axis=ind, keepdims=True)) + tol)
        assert batch.shape == grad.shape
        
        return grad
    
    def _apply_perturbation(self, batch, perturbation, eps):
        clip_min, clip_max = self.classifier.clip_values
        return np.clip(batch + eps * perturbation, clip_min, clip_max)
    
    def _compute(self, x, y, eps):
        adv_x = x.copy()

        # Compute perturbation with implicit batching
        batch_size = 128
        for batch_id in range(adv_x.shape[0] // batch_size + 1):
            batch_index_1, batch_index_2 = batch_id * batch_size, (batch_id + 1) * batch_size
            batch = adv_x[batch_index_1:batch_index_2]
            batch_labels = y[batch_index_1:batch_index_2]

            # Get perturbation
            perturbation = self._compute_perturbation(batch, batch_labels)

            # Apply perturbation and clip
            adv_x[batch_index_1:batch_index_2] = self._apply_perturbation(batch, perturbation, eps)

        return adv_x
