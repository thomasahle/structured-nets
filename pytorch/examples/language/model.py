"""
Modified from pytorch/examples/word_language_model to demonstrate 'StructuredLinear' usage.
"""

import torch.nn as nn
from torch.nn import Parameter
import torch
import numpy as np
import sys
from lstm import LSTM, LSTMCell

class RNNModel(nn.Module):
    """Container module with an encoder, a recurrent module, and a decoder."""

    def __init__(self, class_type, r, rnn_type, ntoken, ninp, nhid, nlayers, dropout=0.5, tie_weights=False):
        super(RNNModel, self).__init__()
        self.drop = nn.Dropout(dropout)
        self.encoder = nn.Embedding(ntoken, ninp)
        if rnn_type in ['LSTM', 'GRU']:
            print('ninp, nhid, nlayers: ', ninp, nhid, nlayers)
            if rnn_type == 'LSTM':
                self.rnn = LSTM(class_type, r, LSTMCell, input_size=ninp, hidden_size=nhid, num_layers=nlayers, dropout=dropout)
            else:
                self.rnn = getattr(nn, rnn_type)(ninp, nhid, nlayers, dropout=dropout)
            # Replace with structured layers
            #self.rnn.weight_ih_l0 = StructuredLinear(None, 'unconstrained', 512, 0.01, 1)
            #self.rnn.weight_ih_l0 = Parameter(torch.Tensor(np.random.random((800,200))))
            #print(self.rnn.weight_ih_l0)
            #quit()
        else:
            try:
                nonlinearity = {'RNN_TANH': 'tanh', 'RNN_RELU': 'relu'}[rnn_type]
            except KeyError:
                raise ValueError( """An invalid option for `--model` was supplied,
                                 options are ['LSTM', 'GRU', 'RNN_TANH' or 'RNN_RELU']""")
            self.rnn = nn.RNN(ninp, nhid, nlayers, nonlinearity=nonlinearity, dropout=dropout)
        self.decoder = nn.Linear(nhid, ntoken)

        # Optionally tie weights as in:
        # "Using the Output Embedding to Improve Language Models" (Press & Wolf 2016)
        # https://arxiv.org/abs/1608.05859
        # and
        # "Tying Word Vectors and Word Classifiers: A Loss Framework for Language Modeling" (Inan et al. 2016)
        # https://arxiv.org/abs/1611.01462
        if tie_weights:
            if nhid != ninp:
                raise ValueError('When using the tied flag, nhid must be equal to emsize')
            self.decoder.weight = self.encoder.weight

        self.init_weights()

        self.rnn_type = rnn_type
        self.nhid = nhid
        self.nlayers = nlayers

    def init_weights(self):
        initrange = 0.1
        self.encoder.weight.data.uniform_(-initrange, initrange)
        self.decoder.bias.data.zero_()
        self.decoder.weight.data.uniform_(-initrange, initrange)

    def forward(self, input, hidden):
        emb = self.drop(self.encoder(input))
        #print('hidden: ', hidden.shape)
        #print('emb, hidden: ', emb.shape, hidden[0].shape, hidden[1].shape)
        output, hidden = self.rnn(emb, hx=hidden)
        output = output.squeeze()
        hidden = (hidden[0].squeeze(0), hidden[1].squeeze(0))
        #print('output, hidden: ', output.shape, hidden[0].shape, hidden[1].shape)
        #quit()
        output = self.drop(output)
        decoded = self.decoder(output.view(output.size(0)*output.size(1), output.size(2)))
        return decoded.view(output.size(0), output.size(1), decoded.size(1)), hidden

    def init_hidden(self, bsz):
        weight = next(self.parameters())
        if self.rnn_type == 'LSTM':
            return (weight.new_zeros(self.nlayers, bsz, self.nhid),
                    weight.new_zeros(self.nlayers, bsz, self.nhid))
        else:
            return weight.new_zeros(self.nlayers, bsz, self.nhid)
