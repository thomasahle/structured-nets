from tensorflow.examples.tutorials.mnist import input_data
import numpy as np
import sys
from scipy.linalg import solve_sylvester
import pickle as pkl
from scipy.ndimage.interpolation import zoom
from sklearn.preprocessing import OneHotEncoder
sys.path.insert(0, '../../../../')
from utils import *

class Dataset:
	# here n is the input size.
	# true_test: if True, we test on test set. Otherwise, split training set into train/validation.
	def __init__(self, name, layer_size, num_iters, transform, stochastic_train, test_size=1000, train_size=10000, true_test=False):
		self.name = name
		self.mnist = None
		self.transform = transform
		self.stochastic_train = stochastic_train
		self.num_iters = num_iters
		self.layer_size = layer_size
		self.pert = None
		self.current_batch = 0
		self.true_transform = None
		self.test_size = test_size
		self.train_size = train_size
		self.true_test = true_test
		self.input_size = self.get_input_size()
		self.train_loc = ''
		self.test_loc = ''
		
		if self.name == 'cifar10':
			# Load the first batch
			data_dir = '/dfs/scratch1/thomasat/datasets/cifar10'

			self.test_loc = '/dfs/scratch1/thomasat/datasets/cifar10/test_batch'
			self.num_batches = 5
			self.iters_per_batch = int(self.num_iters/self.num_batches)
			print 'iters per batch: ', self.iters_per_batch
			self.load_train_cifar10(0)
			self.load_test_data()
			self.val_X = self.test_X
			self.val_Y = self.test_Y

		elif self.name == 'mnist':
			data_dir = '/tmp/tensorflow/mnist/input_data'
			self.mnist = input_data.read_data_sets(data_dir, one_hot=True)
			self.test_X = self.mnist.test.images
			self.test_Y = self.mnist.test.labels
		elif self.name == 'mnist_rot':
			self.train_loc = '/dfs/scratch1/thomasat/datasets/mnist_rot/mnist_all_rotation_normalized_float_train_valid.amat'
			self.test_loc = '/dfs/scratch1/thomasat/datasets/mnist_rot/mnist_all_rotation_normalized_float_test.amat'
			self.load_train_data()
		elif self.name == 'mnist_bg_rot':
			self.train_loc = '/dfs/scratch1/thomasat/datasets/mnist_bg_rot/mnist_all_background_images_rotation_normalized_train_valid.amat'
			self.test_loc = '/dfs/scratch1/thomasat/datasets/mnist_bg_rot/mnist_all_background_images_rotation_normalized_test.amat'

			train_size = 11000
			val_size = 1000
			data = np.genfromtxt(self.train_loc)

			# Shuffle
			X = data[:, :-1]
			Y = np.expand_dims(data[:, -1], 1)

			# Y must be one-hot
			enc = OneHotEncoder()
			Y = enc.fit_transform(Y).todense()
			idx = np.arange(0, X.shape[0])
			np.random.shuffle(idx)

			train_idx = idx[0:train_size]
			val_idx = idx[-val_size:]

			assert train_idx.size == train_size
			assert val_idx.size == val_size

			self.train_X = X[train_idx, :]
			self.train_Y = Y[train_idx, :]
			self.val_X = X[val_idx, :]
			self.val_Y = Y[val_idx, :]

			print self.val_X.shape, self.val_Y.shape, self.train_X.shape, self.train_Y.shape 


		elif self.name == 'mnist_rand_bg':
			self.train_loc = '/dfs/scratch1/thomasat/datasets/mnist_rand_bg/mnist_background_random_train.amat'
			self.test_loc = '/dfs/scratch1/thomasat/datasets/mnist_rand_bg/mnist_background_random_test.amat'
			self.load_train_data()
		elif self.name.startswith('mnist_noise'):
			idx = self.name[-1]
			data_loc = '/dfs/scratch1/thomasat/datasets/mnist_noise/mnist_noise_variations_all_' + idx + '.amat'
			train_size = 11000
			val_size = 1000
			test_size = 2000 # As specified in http://www.iro.umontreal.ca/~lisa/twiki/bin/view.cgi/Public/DeepVsShallowComparisonICML2007#Downloadable_datasets

			data = np.genfromtxt(data_loc)
			X = data[:, :-1]
			Y = np.expand_dims(data[:, -1], 1)

			# Y must be one-hot
			enc = OneHotEncoder()
			Y = enc.fit_transform(Y).todense()
			# Split into train, val, test
			# Shuffle the data
			idx = np.arange(0, X.shape[0])
			np.random.shuffle(idx)

			train_idx = idx[0:train_size]
			val_idx = idx[train_size:train_size+val_size]
			test_idx = idx[-test_size:]

			assert train_idx.size == train_size
			assert val_idx.size == val_size
			assert test_idx.size == test_size

			self.val_X = X[val_idx, :]
			self.val_Y = Y[val_idx, :]
			self.test_X = X[test_idx, :]
			self.test_Y = Y[test_idx, :]
			self.train_X = X[train_idx, :]
			self.train_Y = Y[train_idx, :]

			print self.val_X.shape, self.val_Y.shape, self.test_X.shape, self.test_Y.shape, self.train_X.shape, self.train_Y.shape 

		elif self.name == 'convex':
			self.train_loc = '/dfs/scratch1/thomasat/datasets/convex/convex_train.amat'
			self.test_loc = '/dfs/scratch1/thomasat/datasets/convex/50k/convex_test.amat'
			self.load_train_data()
		elif self.name == 'rect':
			self.train_loc = '/dfs/scratch1/thomasat/datasets/rect/rectangles_train.amat'
			self.test_loc = '/dfs/scratch1/thomasat/datasets/rect/rectangles_test.amat'

			train_size = 1100
			val_size = 100
			data = np.genfromtxt(self.train_loc)

			# Shuffle
			X = data[:, :-1]
			Y = np.expand_dims(data[:, -1], 1)

			# Y must be one-hot
			enc = OneHotEncoder()
			Y = enc.fit_transform(Y).todense()
			idx = np.arange(0, X.shape[0])
			np.random.shuffle(idx)

			train_idx = idx[0:train_size]
			val_idx = idx[-val_size:]

			assert train_idx.size == train_size
			assert val_idx.size == val_size

			self.train_X = X[train_idx, :]
			self.train_Y = Y[train_idx, :]
			self.val_X = X[val_idx, :]
			self.val_Y = Y[val_idx, :]

			print self.val_X.shape, self.val_Y.shape, self.train_X.shape, self.train_Y.shape

		elif self.name == 'rect_images':
			self.train_loc = '/dfs/scratch1/thomasat/datasets/rect_images/rectangles_im_train.amat'
			self.test_loc = '/dfs/scratch1/thomasat/datasets/rect_images/rectangles_im_test.amat'

			train_size = 11000
			val_size = 1000
			data = np.genfromtxt(self.train_loc)

			# Shuffle
			X = data[:, :-1]
			Y = np.expand_dims(data[:, -1], 1)

			# Y must be one-hot
			enc = OneHotEncoder()
			Y = enc.fit_transform(Y).todense()
			idx = np.arange(0, X.shape[0])
			np.random.shuffle(idx)

			train_idx = idx[0:train_size]
			val_idx = idx[-val_size:]

			assert train_idx.size == train_size
			assert val_idx.size == val_size

			self.train_X = X[train_idx, :]
			self.train_Y = Y[train_idx, :]
			self.val_X = X[val_idx, :]
			self.val_Y = Y[val_idx, :]

			print self.val_X.shape, self.val_Y.shape, self.train_X.shape, self.train_Y.shape 

		elif self.name == 'true_pert_circ_T':
			# Generate matrix which satisfies M - MB = Q, for a circulant sparsity transpose pattern B
			# Generate B
			f = 1
			r = 1
			v = np.random.random(self.layer_size-1)
			B = gen_Z_f(self.layer_size, f, v).T

			# Solve sylvester equation
			G = np.random.uniform(low=0.0, high=1.0, size=(self.layer_size, r))
			H = np.random.uniform(low=0.0, high=1.0, size=(self.layer_size, r))

			Q = np.dot(G, H.T)

			I = np.eye(self.layer_size)
			M = solve_sylvester(I, -B, Q)

			self.true_transform = M
			self.pert = B
			test_X, test_Y = gen_batch(self.true_transform, self.test_size, self.pert)
			val_X, val_Y = gen_batch(self.true_transform, self.test_size, self.pert)
			self.test_X = test_X	
			self.test_Y = test_Y
			self.val_X = val_X
			self.val_Y = val_Y

		elif self.name.startswith('true'):
			self.true_transform = gen_matrix(self.input_size, self.name.split("true_",1)[1] )
			test_X, test_Y = gen_batch(self.true_transform, self.test_size)
			val_X, val_Y = gen_batch(self.true_transform, self.test_size)
			self.test_X = test_X	
			self.test_Y = test_Y
			self.val_X = val_X
			self.val_Y = val_Y

			if not self.stochastic_train:
				train_X, train_Y = gen_batch(self.true_transform, self.train_size)				
				self.train_X = train_X	
				self.train_Y = train_Y
		else:
			print 'Not supported: ', self.name
			assert 0

	def get_input_size(self):
		if 'mnist' in self.name:
			return 784
		elif self.name == 'cifar10':
			return 3072
			if self.transform == 'grayscale':
				return 1024
			elif self.transform == 'downsample':
				return 768
		elif self.name.startswith('true_'):
			return self.layer_size	
		else:
			print 'Name not recognized: ', name
			assert 0

	def process_cifar10(self, data):
		if self.transform == 'grayscale':
			n = data.shape[0]
			im_r = data[:, 0:1024].reshape((n, 32, 32))
			im_g = data[:, 1024:2048].reshape((n, 32, 32))
			im_b = data[:, 2048:].reshape((n, 32, 32))
			img = np.stack((im_r, im_g, im_b), axis=-1)
			avg_img = np.mean(img, axis=-1)
			data = avg_img.reshape((n, 32*32))
		elif self.transform == 'downsample':
			n = data.shape[0]

			im_r = data[:, 0:1024].reshape((n, 32, 32))
			im_g = data[:, 1024:2048].reshape((n, 32, 32))
			im_b = data[:, 2048:].reshape((n, 32, 32))

			im_r = zoom(im_r, zoom=(1, 0.5, 0.5), order=0)
			im_g = zoom(im_g, zoom=(1, 0.5, 0.5), order=0)
			im_b = zoom(im_b, zoom=(1, 0.5, 0.5), order=0)

			img = np.stack((im_r, im_g, im_b), axis=-1)
			data = img.reshape((n, 16*16*3))

					
		return data / 255.0
	
	def load_train_cifar10(self, batch_num):
		# 0-indexing of batch_num
		loc = '/dfs/scratch1/thomasat/datasets/cifar10/data_batch_' + str(batch_num+1)
		dict = pkl.load(open(loc, 'rb'))
		data = dict['data']
		labels = np.array(dict['labels'])


		# Convert to grayscale
		reshaped = self.process_cifar10(data)

		self.train_X = reshaped
		self.train_Y = np.expand_dims(labels, 1)

		# Y must be one-hot
		enc = OneHotEncoder()
		self.train_Y = enc.fit_transform(self.train_Y).todense()			

		print 'batch, train_X.shape, train_Y.shape: ', batch_num, self.train_X.shape, self.train_Y.shape


	def out_size(self):
		if self.name in ['convex', 'rect', 'rect_images']:
			return 2
		elif 'mnist' in self.name or 'cifar10' in self.name:
			return 10
		else:
			return self.input_size

	def load_test_data(self):
		if self.name.startswith('mnist_noise'):
			return 

		if self.name == 'cifar10':
			test_dict = pkl.load(open(self.test_loc, 'rb'))
			test_data = test_dict['data']
			test_labels = np.array(test_dict['labels'])

			test_data = self.process_cifar10(test_data)

			self.test_X = test_data
			self.test_Y = np.expand_dims(test_labels, 1)

			# Y must be one-hot
			enc = OneHotEncoder()
			self.test_Y = enc.fit_transform(self.test_Y).todense()		


		elif self.test_loc:
			test_data = np.genfromtxt(self.test_loc)

			self.test_X = test_data[:, :-1]
			self.test_Y = np.expand_dims(test_data[:, -1], 1)

			# Y must be one-hot
			enc = OneHotEncoder()
			self.test_Y = enc.fit_transform(self.test_Y).todense()		

	def load_train_data(self):
		train_data = np.genfromtxt(self.train_loc)

		self.train_X = train_data[:, :-1]
		self.train_Y = np.expand_dims(train_data[:, -1], 1)

		# Y must be one-hot
		enc = OneHotEncoder()
		self.train_Y = enc.fit_transform(self.train_Y).todense()

		"""
		else: # Use train_loc only
			data = np.genfromtxt(train_loc)
			# Last self.test_size examples are for validation
			# Last column is true class

			self.train_X = data[:-self.test_size, :-1]
			self.train_Y = np.expand_dims(data[:-self.test_size, -1], 1)
			self.test_X = data[-self.test_size:, :-1]
			self.test_Y = np.expand_dims(data[-self.test_size:, -1], 1)

			# Y must be one-hot
			enc = OneHotEncoder()
			self.train_Y = enc.fit_transform(self.train_Y).todense()
			self.test_Y = enc.fit_transform(self.test_Y).todense()
		"""

	def batch(self, batch_size, step):
		if self.name == 'mnist':
			batch_xs, batch_ys = self.mnist.train.next_batch(batch_size)
			return batch_xs, batch_ys
		elif self.name.startswith('mnist') or self.name in ['convex', 'rect', 'rect_images']:
			# Randomly sample batch_size from train_X and train_Y
			idx = np.random.randint(self.train_X.shape[0], size=batch_size)
			return self.train_X[idx, :], self.train_Y[idx, :]
		elif self.name == 'cifar10':
			this_batch = int(step/self.iters_per_batch)
			if this_batch != self.current_batch:
				self.load_train_cifar10(this_batch)
				# Load new data
				self.current_batch = this_batch
			idx = np.random.randint(self.train_X.shape[0], size=batch_size)
			return self.train_X[idx, :], self.train_Y[idx, :]			
		elif self.name.startswith('true'):
			if self.stochastic_train:
				return gen_batch(self.true_transform, batch_size, self.pert)
			else:
				idx = np.random.randint(self.train_X.shape[0], size=batch_size)
				return self.train_X[idx, :], self.train_Y[idx, :]
		else:
			print 'Not supported: ', name
			assert 0

