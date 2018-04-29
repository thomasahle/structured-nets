import functools
import numpy as np

import torch

import cufat as cf
from triextrafat import krylov_construct
# from triXXF import KrylovTransposeMultiply

from complex_utils import complex_mult_, conjugate
import fft_utils as fu


device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

def krylov_transpose_multiply(subdiag, v, u):
    """Multiply Krylov(A, v_i)^T @ u when A is zero except on the subdiagonal.
    Parameters:
        subdiag: Tensor of shape (n - 1, )
        v: Tensor of shape (rank, n)
        u: Tensor of shape (batch_size, n)
    Returns:
        product: Tensor of shape (batch_size, rank, n)
    """
    batch_size, n = u.shape
    rank, n_ = v.shape
    assert n == n_, 'u and v must have the same last dimension'
    m = int(np.log2(n))
    assert n == 1 << m, 'n must be a power of 2'

    T_00 = u[:, np.newaxis, ..., np.newaxis] * v[np.newaxis, ..., np.newaxis]
    T_01 = u[..., np.newaxis]
    T_10 = v[..., np.newaxis]
    T_11 = torch.ones((n, 1), device=T_00.device)
    for d in range(m)[::-1]:
        n1, n2 = 1 << d, 1 << (m - d - 1)
        S_00, S_01, S_10, S_11 = T_00, T_01, T_10, T_11
        S0_10 = torch.cat((S_10[:, ::2], torch.zeros_like(S_10[:, ::2])), dim=-1)
        S1_01 = torch.cat((S_01[:, 1::2], torch.zeros_like(S_01[:, 1::2])), dim=-1)
        S0_11 = torch.cat((S_11[::2], torch.zeros_like(S_11[::2])), dim=-1)
        S1_11 = torch.cat((S_11[1::2], torch.zeros_like(S_11[1::2])), dim=-1)
        S = torch.cat((S0_10, S0_11[np.newaxis], S1_01, S1_11[np.newaxis]))

        # polynomial multiplications
        S_f = torch.rfft(S, 1)
        S0_10_f, S0_11_f, S1_01_f, S1_11_f = S_f[:rank], S_f[rank], S_f[rank+1:rank+1+batch_size], S_f[-1]
        T_00_f = complex_mult_(S1_01_f[:, np.newaxis], S0_10_f[np.newaxis])
        T_01_f = complex_mult_(S1_01_f, S0_11_f)
        T_10_f = complex_mult_(S1_11_f, S0_10_f)
        T_11_f = complex_mult_(S1_11_f, S0_11_f)

        T_f = torch.cat((torch.cat((T_00_f, T_01_f[:, np.newaxis]), dim=1),
                         torch.cat((T_10_f[np.newaxis], T_11_f[np.newaxis, np.newaxis]), dim=1)))

        T = torch.irfft(T_f, 1, signal_sizes=(2 * n2, )) * subdiag[(n2 - 1)::(2 * n2), np.newaxis]
        T_00, T_01, T_10, T_11 = T[:batch_size, :rank], T[:batch_size, -1], T[-1, :rank], T[-1, -1]

        # polynomial additions
        T_00 = torch.cat((T_00[:, :, :, :n2], T_00[:, :, :, n2:] + S_00[:, :, ::2] + S_00[:, :, 1::2]), dim=-1)
        T_01 = torch.cat((T_01[:, :, :n2], T_01[:, :, n2:] + S_01[:, ::2]), dim=-1)
        T_10 = torch.cat((T_10[:, :, :n2], T_10[:, :, n2:] + S_10[:, 1::2]), dim=-1)

    # Negative step isn't supported by Pytorch
    # (https://github.com/pytorch/pytorch/issues/229) so we have to construct
    # the index explicitly.
    reverse_index = torch.arange(n - 1, -1, -1, dtype=torch.long, device=T_00.device)
    return T_00[:, :, :, reverse_index].squeeze(dim=2)


def krylov_transpose_multiply_mine(subdiag, v, u):
    """Multiply Krylov(A, v_i)^T @ u when A is zero except on the subdiagonal.
    Use my own CuFFT wrapper, so it's about 5% faster than pytorch's FFT.

    Parameters:
        subdiag: Tensor of shape (n - 1, )
        v: Tensor of shape (rank, n)
        u: Tensor of shape (batch_size, n)
    Returns:
        product: Tensor of shape (batch_size, rank, n)
    """
    batch_size, n = u.shape
    rank, n_ = v.shape
    assert n == n_, 'u and v must have the same last dimension'
    m = int(np.log2(n))
    assert n == 1 << m, 'n must be a power of 2'

    T_00 = u[:, np.newaxis, ..., np.newaxis] * v[np.newaxis, ..., np.newaxis]
    T_01 = u[..., np.newaxis]
    T_10 = v[..., np.newaxis]
    T_11 = torch.ones((n, 1), device=T_00.device)
    for d in range(m)[::-1]:
        n1, n2 = 1 << d, 1 << (m - d - 1)
        S_00, S_01, S_10, S_11 = T_00, T_01, T_10, T_11
        S0_10 = torch.cat((S_10[:, ::2], torch.zeros_like(S_10[:, ::2])), dim=-1)
        S1_01 = torch.cat((S_01[:, 1::2], torch.zeros_like(S_01[:, 1::2])), dim=-1)
        S0_11 = torch.cat((S_11[::2], torch.zeros_like(S_11[::2])), dim=-1)
        S1_11 = torch.cat((S_11[1::2], torch.zeros_like(S_11[1::2])), dim=-1)
        S = torch.cat((S0_10, S0_11[np.newaxis], S1_01, S1_11[np.newaxis]))

        # polynomial multiplications
        S_f = fu.rfft(S)
        S0_10_f, S0_11_f, S1_01_f, S1_11_f = S_f[:rank], S_f[rank], S_f[rank+1:rank+1+batch_size], S_f[-1]
        T_00_f = complex_mult_(S1_01_f[:, np.newaxis], S0_10_f[np.newaxis])
        T_01_f = complex_mult_(S1_01_f, S0_11_f)
        T_10_f = complex_mult_(S1_11_f, S0_10_f)
        T_11_f = complex_mult_(S1_11_f, S0_11_f)

        T_f = torch.cat((torch.cat((T_00_f, T_01_f[:, np.newaxis]), dim=1),
                         torch.cat((T_10_f[np.newaxis], T_11_f[np.newaxis, np.newaxis]), dim=1)))

        T = fu.irfft(T_f) * subdiag[(n2 - 1)::(2 * n2), np.newaxis]
        T_00, T_01, T_10, T_11 = T[:batch_size, :rank], T[:batch_size, -1], T[-1, :rank], T[-1, -1]

        # polynomial additions
        T_00 = torch.cat((T_00[:, :, :, :n2], T_00[:, :, :, n2:] + S_00[:, :, ::2] + S_00[:, :, 1::2]), dim=-1)
        T_01 = torch.cat((T_01[:, :, :n2], T_01[:, :, n2:] + S_01[:, ::2]), dim=-1)
        T_10 = torch.cat((T_10[:, :, :n2], T_10[:, :, n2:] + S_10[:, 1::2]), dim=-1)

    # Negative step isn't supported by Pytorch
    # (https://github.com/pytorch/pytorch/issues/229) so we have to construct
    # the index explicitly.
    reverse_index = torch.arange(n - 1, -1, -1, dtype=torch.long, device=T_00.device)
    return T_00[:, :, :, reverse_index].squeeze(dim=2)


def krylov_multiply_by_autodiff(subdiag, v, w):
    """Multiply \sum_i Krylov(A, v_i) @ w_i when A is zero except on the subdiagonal, using Pytorch's autodiff.
    Parameters:
        subdiag: Tensor of shape (n - 1, )
        v: Tensor of shape (rank, n)
        w: Tensor of shape (batch_size, rank, n)
    Returns:
        product: Tensor of shape (batch_size, n)
    """
    batch_size, rank, n = w.shape
    rank_, n_ = v.shape
    assert n == n_, 'w and v must have the same last dimension'
    assert rank == rank_, 'w and v must have the same rank'
    m = int(np.log2(n))
    assert n == 1 << m, 'n must be a power of 2'

    u = torch.zeros((batch_size, n), dtype=v.dtype, device=v.device, requires_grad=True)
    prod = krylov_transpose_multiply(subdiag, v, u)
    result, = torch.autograd.grad(prod, u, grad_outputs=w, create_graph=True)
    return result


def krylov_multiply_forward(subdiag, v):
    rank, n = v.shape
    m = int(np.log2(n))
    assert n == 1 << m, 'n must be a power of 2'

    save_for_backward = [None] * m
    T_10 = v[..., np.newaxis]
    T_11 = torch.ones((n, 1), device=T_10.device)
    for d in range(m)[::-1]:
        n1, n2 = 1 << d, 1 << (m - d - 1)
        S_10, S_11 = T_10, T_11
        S0_10 = torch.cat((S_10[:, ::2], torch.zeros_like(S_10[:, ::2])), dim=-1)
        S0_11 = torch.cat((S_11[::2], torch.zeros_like(S_11[::2])), dim=-1)
        S1_11 = torch.cat((S_11[1::2], torch.zeros_like(S_11[1::2])), dim=-1)
        S = torch.cat((S0_10, S0_11[np.newaxis], S1_11[np.newaxis]))

        # polynomial multiplications
        S_f = torch.rfft(S, 1)
        S0_10_f, S0_11_f, S1_11_f = S_f[:rank], S_f[-2], S_f[-1]
        save_for_backward[d] = (S0_10_f, S0_11_f)

        T_10_f = complex_mult_(S1_11_f, S0_10_f)
        T_11_f = complex_mult_(S1_11_f, S0_11_f)

        T_f = torch.cat((T_10_f, T_11_f[np.newaxis]))

        T = torch.irfft(T_f, 1, signal_sizes=(2 * n2, )) * subdiag[(n2 - 1)::(2 * n2), np.newaxis]
        T_10, T_11 = T[:rank], T[-1]

        # polynomial additions
        T_10 = torch.cat((T_10[:, :, :n2], T_10[:, :, n2:] + S_10[:, 1::2]), dim=-1)

    return save_for_backward

def krylov_multiply(subdiag, v, w):
    """Multiply \sum_i Krylov(A, v_i) @ w_i when A is zero except on the subdiagonal.
    Parameters:
        subdiag: Tensor of shape (n - 1, )
        v: Tensor of shape (rank, n)
        w: Tensor of shape (batch_size, rank, n)
    Returns:
        product: Tensor of shape (batch_size, n)
    """
    batch_size, rank, n = w.shape
    rank_, n_ = v.shape
    assert n == n_, 'w and v must have the same last dimension'
    assert rank == rank_, 'w and v must have the same rank'
    m = int(np.log2(n))
    assert n == 1 << m, 'n must be a power of 2'

    save_for_backward = krylov_multiply_forward_mine(subdiag, v)
    reverse_index = torch.arange(n - 1, -1, -1, dtype=torch.long, device=w.device)
    w = w[:, :, np.newaxis, :]
    dT_00, dT_01 = w[:, :, :, reverse_index], torch.zeros((batch_size, 1, n), dtype=w.dtype, device=w.device)

    for d in range(m):
        n1, n2 = 1 << d, 1 << (m - d - 1)
        dS_00 = torch.empty((batch_size, rank, 2 * n1, n2), device=w.device)
        dS_00[:, :, ::2] = dT_00[:, :, :, n2:]
        dS_00[:, :, 1::2] = dT_00[:, :, :, n2:]
        dS_01 = torch.empty((batch_size, 2 * n1, n2), device=w.device)
        dS_01[:, ::2] = dT_01[:, :, n2:]

        dT = torch.cat((dT_00, dT_01[:, np.newaxis]), dim=1)
        dT = dT * subdiag[(n2 - 1)::(2 * n2), np.newaxis]

        dT_f = torch.rfft(dT, 1) / (2 * n2)
        dT_00_f, dT_01_f = dT_f[:, :rank], dT_f[:, -1]

        S0_10_f, S0_11_f = save_for_backward[d]
        dS1_01_f = complex_mult_(conjugate(S0_10_f)[np.newaxis], dT_00_f).sum(dim=1) + complex_mult_(conjugate(S0_11_f), dT_01_f)

        dS1_01 = torch.irfft(dS1_01_f, 1, signal_sizes=(2 * n2, )) * (2 * n2)
        dS_01[:, 1::2] = dS1_01[:, :, :n2]

        dT_00, dT_01 = dS_00, dS_01

    du = ((dT_00 * v[np.newaxis, :, :, np.newaxis]).sum(dim=1) + dT_01).squeeze(dim=-1)
    return du

def krylov_multiply_forward_mine(subdiag, v):
    rank, n = v.shape
    m = int(np.log2(n))
    assert n == 1 << m, 'n must be a power of 2'

    save_for_backward = [None] * m
    T_10 = v[..., np.newaxis]
    T_11 = torch.ones((n, 1), device=T_10.device)
    for d in range(m)[::-1]:
        n1, n2 = 1 << d, 1 << (m - d - 1)
        S_10, S_11 = T_10, T_11
        S0_10 = torch.cat((S_10[:, ::2], torch.zeros_like(S_10[:, ::2])), dim=-1)
        S0_11 = torch.cat((S_11[::2], torch.zeros_like(S_11[::2])), dim=-1)
        S1_11 = torch.cat((S_11[1::2], torch.zeros_like(S_11[1::2])), dim=-1)
        S = torch.cat((S0_10, S0_11[np.newaxis], S1_11[np.newaxis]))

        # polynomial multiplications
        S_f = fu.rfft(S)
        S0_10_f, S0_11_f, S1_11_f = S_f[:rank], S_f[-2], S_f[-1]
        save_for_backward[d] = (S0_10_f, S0_11_f)

        T_10_f = complex_mult_(S1_11_f, S0_10_f)
        T_11_f = complex_mult_(S1_11_f, S0_11_f)

        T_f = torch.cat((T_10_f, T_11_f[np.newaxis]))

        T = fu.irfft(T_f) * subdiag[(n2 - 1)::(2 * n2), np.newaxis]
        T_10, T_11 = T[:rank], T[-1]

        # polynomial additions
        T_10 = torch.cat((T_10[:, :, :n2], T_10[:, :, n2:] + S_10[:, 1::2]), dim=-1)

    return save_for_backward

def krylov_multiply_mine(subdiag, v, w):
    """Multiply \sum_i Krylov(A, v_i) @ w_i when A is zero except on the subdiagonal.
    Use my own CuFFT wrapper, so it's about 5% faster than pytorch's FFT.
    Parameters:
        subdiag: Tensor of shape (n - 1, )
        v: Tensor of shape (rank, n)
        w: Tensor of shape (batch_size, rank, n)
    Returns:
        product: Tensor of shape (batch_size, n)
    """
    batch_size, rank, n = w.shape
    rank_, n_ = v.shape
    assert n == n_, 'w and v must have the same last dimension'
    assert rank == rank_, 'w and v must have the same rank'
    m = int(np.log2(n))
    assert n == 1 << m, 'n must be a power of 2'

    save_for_backward = krylov_multiply_forward_mine(subdiag, v)
    reverse_index = torch.arange(n - 1, -1, -1, dtype=torch.long, device=w.device)
    w = w[:, :, np.newaxis, :]
    dT_00, dT_01 = w[:, :, :, reverse_index], torch.zeros((batch_size, 1, n), dtype=w.dtype, device=w.device)

    for d in range(m):
        n1, n2 = 1 << d, 1 << (m - d - 1)
        dS_00 = torch.empty((batch_size, rank, 2 * n1, n2), device=w.device)
        dS_00[:, :, ::2] = dT_00[:, :, :, n2:]
        dS_00[:, :, 1::2] = dT_00[:, :, :, n2:]
        dS_01 = torch.empty((batch_size, 2 * n1, n2), device=w.device)
        dS_01[:, ::2] = dT_01[:, :, n2:]

        dT = torch.cat((dT_00, dT_01[:, np.newaxis]), dim=1)
        dT = dT * subdiag[(n2 - 1)::(2 * n2), np.newaxis]

        dT_f = fu.rfft(dT) / (2 * n2)
        dT_00_f, dT_01_f = dT_f[:, :rank], dT_f[:, -1]

        S0_10_f, S0_11_f = save_for_backward[d]
        dS1_01_f = complex_mult_(conjugate(S0_10_f)[np.newaxis], dT_00_f).sum(dim=1) + complex_mult_(conjugate(S0_11_f), dT_01_f)

        dS1_01 = fu.irfft(dS1_01_f) * (2 * n2)
        dS_01[:, 1::2] = dS1_01[:, :, :n2]

        dT_00, dT_01 = dS_00, dS_01

    du = ((dT_00 * v[np.newaxis, :, :, np.newaxis]).sum(dim=1) + dT_01).squeeze(dim=-1)
    return du


def subd_mult(subd_A, subd_B, G, H, x):
    rank, n = G.shape
    batch_size = x.shape[0]
    KT_out = krylov_transpose_multiply(subd_B, H, x)
    K_out = krylov_multiply(subd_A, G, KT_out)
    return K_out


def test_transpose_multiply():
    m = 12
    n = 1<<m
    batch_size = 512
    rank = 3
    subdiag = torch.rand(n-1, requires_grad=True, device=device)
    A = np.diag(subdiag.data.cpu().numpy(), -1)
    u = torch.rand((batch_size, n), requires_grad=True, device=device)
    v = torch.rand((rank, n), requires_grad=True, device=device)
    result = krylov_transpose_multiply(subdiag, v, u)
    grad,  = torch.autograd.grad(torch.sum(result), v, retain_graph=True)
    grad = grad.data.cpu().numpy()
    result = result.data.cpu().numpy()
    # Use my own CuFFT wrapper
    result_mine = krylov_transpose_multiply_mine(subdiag, v, u)
    grad_mine, = torch.autograd.grad(torch.sum(result_mine), v, retain_graph=True)
    grad_mine = grad_mine.data.cpu().numpy()
    result_mine = result_mine.data.cpu().numpy()
    # CPU dense multiply
    Ks = [krylov_construct(A, v.data.cpu().numpy()[i], n) for i in range(rank)]
    u_cpu = u.data.cpu().numpy()
    result2 = np.stack([u_cpu @ K.T for K in Ks])
    result2 = result2.swapaxes(0, 1).squeeze()
    # GPU dense multiply
    Ks_pytorch = [torch.Tensor(K).cuda() for K in Ks]
    result3 = torch.stack([u @ K.t() for K in Ks_pytorch])
    result3 = result3.data.cpu().numpy().swapaxes(0, 1).squeeze()
    # Explicit construction on GPU
    linear_fn = functools.partial(shift_subdiag, subdiag)
    Ks_gpu = [Krylov(linear_fn, v_) for v_ in v]
    result4 = torch.stack([u @ K for K in Ks_gpu])
    result4 = result4.data.cpu().numpy().swapaxes(0, 1).squeeze()
    # np.allclose(result_mine, result2)
    print(np.max(abs(result - result_mine)))
    print(np.mean(abs(result - result_mine)))
    print(np.max(abs(grad - grad_mine)))
    print(np.mean(abs(grad - grad_mine)))
    print(np.max(abs(result - result2)))
    print(np.mean(abs(result - result2)))
    print(np.max(abs(result3 - result2)))
    print(np.mean(abs(result3 - result2)))
    print(np.max(abs(result4 - result2)))
    print(np.mean(abs(result4 - result2)))


def test_multiply():
    m = 12
    n = 1 << m
    batch_size = 512
    rank = 3
    subdiag = torch.rand(n-1, requires_grad=True, device=device)
    A = np.diag(subdiag.data.cpu().numpy(), -1)
    u = torch.rand((batch_size, n), requires_grad=True, device=device)
    v = torch.rand((rank, n), requires_grad=True, device=device)
    w = torch.rand((batch_size, rank, n), requires_grad=True, device=device)
    result = krylov_multiply(subdiag, v, w)
    grad, = torch.autograd.grad(torch.sum(result), v, retain_graph=True)
    grad = grad.data.cpu().numpy()
    result = result.data.cpu().numpy()
    # Use my own wrapper of CuFFT
    result_mine = krylov_multiply_mine(subdiag, v, w)
    grad_mine,  = torch.autograd.grad(torch.sum(result_mine), v, retain_graph=True)
    grad_mine = grad_mine.data.cpu().numpy()
    result_mine = result_mine.data.cpu().numpy()
    # Using autodiff
    result1 = krylov_multiply_by_autodiff(subdiag, v, w)
    result1 = result1.data.cpu().numpy()
    # CPU dense multiply
    Ks = [krylov_construct(A, v.data.cpu().numpy()[i], n) for i in range(rank)]
    w_cpu = w.data.cpu().numpy()
    result2 = np.stack([w_cpu[:, i] @ Ks[i] for i in range(rank)]).sum(axis=0)
    result2 = result2.squeeze()
    assert np.allclose(result_mine, result)
    assert np.allclose(result, result1)
    assert np.allclose(result1, result2)
    print(np.max(abs(result_mine - result)))
    print(np.mean(abs(result_mine - result)))
    print(np.max(abs(grad_mine - grad)))
    print(np.mean(abs(grad_mine - grad)))
    print(np.max(abs(result_mine - result1)))
    print(np.mean(abs(result_mine - result1)))
    print(np.max(abs(result1 - result2)))
    print(np.mean(abs(result1 - result2)))

    # Combine transpose multiply follow by non-transpose multiply
    result = krylov_multiply_mine(subdiag, v, krylov_transpose_multiply_mine(subdiag, v, u))


def test_misc():
    pass
    # epsilon = 1e-5
    # for i in range(2):
    #     one_hot = Variable(torch.zeros_like(u.data))
    #     one_hot[0, i] = epsilon
    #     u_new = u + one_hot
    #     u_new_minus = u - one_hot
    #     print((torch.sum(cf.Rfft_slow(u_new)[0]) - torch.sum(cf.Rfft_slow(u_new_minus)[0])) / (2 * epsilon))

def shift(v, f=1):
    return torch.cat((f * v[[v.size(0) - 1]], v[:-1]))

def shift_subdiag(subdiag, v, f=0.0):
    return torch.cat((f * v[[v.size(0) - 1]], subdiag * v[:-1]))

def Krylov(linear_map, v, n=None):
    if n is None:
        n = v.size(0)
    cols = [v]
    for _ in range(n - 1):
        v = linear_map(v)
        cols.append(v)
    return torch.stack(cols, dim=-1)


if __name__ == "__main__":
    test_transpose_multiply()
    test_multiply()
