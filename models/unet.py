import torch
import torch.nn as nn
from models.blocks import get_time_embedding
from models.blocks import DownBlock, MidBlock, UpBlock



class UNet(nn.Module):
    def __init__(self, im_channels, model_config):
        super().__init__()
        self.down_channels = model_config['down_channels']
        self.mid_channels = model_config['mid_channels']
        self.t_emb_dim = model_config['time_emb_dim']
        self.down_sample = model_config['down_sample']
        self.num_down_layers = model_config['num_down_layers']
        self.num_mid_layers = model_config['num_mid_layers']
        self.num_up_layers = model_config['num_up_layers']
        self.attns = model_config['attn_down']
        self.norm_channels = model_config['norm_channels']
        self.num_heads = model_config['num_heads']
        self.conv_out_channels = model_config['conv_out_channels']

        assert self.mid_channels[0] == self.down_channels[-1]
        assert self.mid_channels[-1] == self.down_channels[-2]
        assert len(self.down_sample) == len(self.down_channels) - 1
        assert len(self.attns) == len(self.down_channels) - 1

        self.t_proj = nn.Sequential(
            nn.Linear(self.t_emb_dim, self.t_emb_dim),
            nn.SiLU(),
            nn.Linear(self.t_emb_dim, self.t_emb_dim)
        )
        self.up_sample = list(reversed(self.down_sample))
        self.conv_in = nn.Conv2d(im_channels, self.down_channels[0], kernel_size=3, padding=1)

        self.downs = nn.ModuleList([])
        for i in range(len(self.down_channels) - 1):
            self.downs.append(DownBlock(self.down_channels[i], self.down_channels[i+1], self.t_emb_dim,
                                        down_sample=self.down_sample[i],
                                        num_heads=self.num_heads,
                                        num_layers=self.num_down_layers,
                                        attn=self.attns[i],
                                        norm_channels=self.norm_channels))

        self.mids = nn.ModuleList([])
        for i in range(len(self.mid_channels) - 1):
            self.mids.append(MidBlock(self.mid_channels[i], self.mid_channels[i+1], self.t_emb_dim,
                                      num_heads=self.num_heads,
                                      num_layers=self.num_mid_layers,
                                      norm_channels=self.norm_channels))

        self.ups = nn.ModuleList([])
        for i in reversed(range(len(self.down_channels) - 1)):
            self.ups.append(UpBlock(self.down_channels[i]*2, self.down_channels[i-1] if i != 0 else self.conv_out_channels,
                                    self.t_emb_dim, up_sample=self.down_sample[i],
                                    num_heads=self.num_heads,
                                    num_layers=self.num_up_layers,
                                    attn = 1 - self.attns[i],
                                    norm_channels=self.norm_channels))

            self.norm_out = nn.GroupNorm(self.norm_channels, self.conv_out_channels)
            self.conv_out = nn.Conv2d(self.conv_out_channels, im_channels, kernel_size=3, padding=1)

    def forward(self, x, t):
        out = self.conv_in(x)
        t_emb = get_time_embedding(torch.as_tensor(t).long(), self.t_emb_dim)
        t_emb = self.t_proj(t_emb)

        down_outs = []
        # down-sampling (repeat 3 times)
        for down in self.downs: # down: variable assigned DownBlock instance(module)
            # print(out.shape)
            down_outs.append(out)
            out = down(out, t_emb) # call forward method & assign down-sampled result to out variable

        # bottleneck (repeat 2 times)
        for mid in self.mids:
            # print(out.shape)
            out = mid(out, t_emb)

        # up-samplig (repeat 3 times)
        for up in self.ups: # up: variable assigned UpBlock instance(module)
            down_out = down_outs.pop()
            # print(out, down_out.shape)
            out = up(out, down_out, t_emb) # call forward method (conduct skip connection) & , assign up-sampled result to out variable
        out = self.norm_out(out)
        out = nn.SiLU()(out)
        out = self.conv_out(out)
        return out
