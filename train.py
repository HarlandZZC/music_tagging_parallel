import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio
import librosa
import numpy as np
import matplotlib.pyplot as plt
import random
import argparse
from pathlib import Path
from torch.utils.data import DataLoader
from torchaudio.transforms import MelSpectrogram
from einops import rearrange
import wandb
# from audidata.datasets import GTZAN

class GTZAN:
    def __init__(self, root, split, sr):
        self.root = root
        self.split = split
        self.sr = sr

        audios_dir = Path(root,"genres")
        labels = os.listdir(audios_dir) 

        self.lb_to_ix = {lb: ix for ix, lb in enumerate(labels)}
        self.ix_to_lb = {ix: lb for ix, lb in enumerate(labels)}
        self.meta_dict = {
            "audio_name": [],
            "audio_path": [],
            "label": [],
            "index": [],
            "target": [],
        }

        for label in labels:
            sub_audios_dir = Path(audios_dir, label)
            audio_names = os.listdir(sub_audios_dir)

            if split == "train":
                audio_names = audio_names[0:90]
            elif split == "valid":
                audio_names = audio_names[90:100]
            elif split == "test":
                audio_names = audio_names[90:100]

            index = self.lb_to_ix[label]
            target = np.zeros(len(labels), dtype=np.float32)
            target[index] = 1 

            self.meta_dict["audio_name"].extend(audio_names)
            self.meta_dict["audio_path"].extend([Path(sub_audios_dir, audio_name) for audio_name in audio_names])
            self.meta_dict["label"].extend([label] * len(audio_names))
            self.meta_dict["index"].extend([index] * len(audio_names))
            self.meta_dict["target"].extend([target] * len(audio_names))
            
    
    def __len__(self):
        audios_num = len(self.meta_dict["audio_name"])
        return audios_num
    
    def __getitem__(self, index:int):
        audio_path = self.meta_dict["audio_path"][index]
        target = self.meta_dict["target"][index]

        audio, fs = librosa.load(audio_path, sr=self.sr, mono=True)
        segment_samples = fs * 30
        audio = librosa.util.fix_length(audio, size=segment_samples, axis=0)

        # log mel feature of audio
        # mel = librosa.feature.melspectrogram(y=audio, sr=fs, n_fft=2048, hop_length=240, n_mels=128)
        # fig, axs = plt.subplots(1)  
        # axs.plot(audio)
        # axs.matshow(np.log(mel), origin="lower", aspect="auto", cmap="jet")
        # fig.savefig("mel.png")

        # wrtie the audio
        # soundfile.write("audio.wav", audio, fs)
        return audio, target
    
class CNN(nn.Module):
    def __init__(self):
        super().__init__()
        
        self.mel_extractor = MelSpectrogram(
            sample_rate=16000,
            n_fft=2048,
            hop_length=240,
            n_mels=128,
            power=2.0,
            normalized=True, 
        )

        self.conv1 = nn.Conv2d(
            in_channels=1,
            out_channels=16,
            kernel_size=(3, 3),
            padding=(1, 1),
            )
        
        self.conv2 = nn.Conv2d(
            in_channels=16,
            out_channels=32,
            kernel_size=(3, 3),
            padding=(1, 1),
            )
        
        self.conv3 = nn.Conv2d(
            in_channels=32,
            out_channels=64,
            kernel_size=(3, 3),
            padding=(1, 1),
            )
        
        self.conv4 = nn.Conv2d(
            in_channels=64,
            out_channels=128,
            kernel_size=(3, 3),
            padding=(1, 1),
            )
        
        self.fc = nn.Linear(128, 10)

    def forward(self, x): 
        x = self.mel_extractor(x) # (B, F, T)
        x = x[:, None, :, :] # (B, 1, F, T)
        x = rearrange(x, "B C F T -> B C T F") 

        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, kernel_size=(2, 2))
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, kernel_size=(2, 2))
        x = F.relu(self.conv3(x))
        x = F.max_pool2d(x, kernel_size=(2, 2))
        x = F.relu(self.conv4(x))
        x = F.max_pool2d(x, kernel_size=(2, 2))
        x, _ = torch.max(x, dim=-1)
        x, _ = torch.max(x, dim=-1)
        x = self.fc(x)

        x = F.sigmoid(x)
        return x
 

def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

def train(root, device_ids, epochs, batch_size, lr):

    wandb.init(
        project="music_tagging_parallel",

        config={
            "epochs": epochs,
            "batch_size": batch_size,
            "lr": lr,
        }
        )
    # epoch_loss_table = wandb.Table(columns=["epoch", "loss"])
    # epoch_acc_table = wandb.Table(columns=["epoch", "acc"])

    train_dataset = GTZAN(
        root = root,
        split = "train",
        sr = 24000,
    )

    train_dataloader = DataLoader(
        dataset = train_dataset,
        batch_size = batch_size,
        num_workers = 8,
        pin_memory=True,
        shuffle=True,
    )

    valid_dataset = GTZAN(
        root = root,
        split = "valid",
        sr = 24000,
    )

    valid_dataloader = DataLoader(
        dataset = valid_dataset,
        batch_size = batch_size,
        num_workers = 8,
        pin_memory=True,
        shuffle=False,
    )

    device = torch.device(f"cuda:{device_ids[0]}")
    model = CNN()
    model = torch.nn.DataParallel(model, device_ids=device_ids).cuda()
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    step = 0
    for epoch in range(1, epochs+1):
        # train
        for audio, target in train_dataloader:
            audio = audio.to(device)
            target = target.to(device)

            output = model(audio)
            loss = F.binary_cross_entropy(output, target) 

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            step += 1

            print("epoch:", epoch, "step:", step, "loss:", loss.item())

        #valid
        if epoch % 1 == 0:
            pred_ids = np.array([])
            target_ids = np.array([])
            for audio, target in valid_dataloader:
                audio = audio.to(device)
                target = target.to(device)

                with torch.no_grad():
                    model.eval()
                    output = model(audio) 
                    pred_id = output.argmax(dim=1).cpu().numpy()
                    target_id = target.argmax(dim=1).cpu().numpy()

                    pred_ids = np.append(pred_ids, pred_id)
                    target_ids = np.append(target_ids, target_id)
                    model.train()              

            acc = (pred_ids == target_ids).mean()
            print("epoch:", epoch, "step:", step, "loss:", loss.item(), "acc:", acc)

            # epoch_loss_table.add_data(epoch, loss.item())
            # epoch_loss_table_plot = wandb.plot.line(epoch_loss_table, "epoch", "loss")
            # wandb.log({"epoch_loss_table": epoch_loss_table_plot})
            wandb.log({"epoch": epoch, "step": step, "loss": loss.item(), "acc": acc})

        # save
        if epoch % 10 == 0:
            if os.path.exists("./checkpoints") == False:
                os.makedirs("./checkpoints")
            if os.path.exists(f"./checkpoints/epoch{epoch}.pth") == True:
                os.remove(f"./checkpoints/epoch{epoch}.pth")
            torch.save(model.state_dict(),
                    f"./checkpoints/epoch{epoch}.pth")

    wandb.finish()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=str, default="/datasets/gtzan")
    parser.add_argument("--device_ids", type=int, nargs='+', default=[1,2])
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch_size", type=int, default=108)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    seed_everything(args.seed)
    train(args.root, args.device_ids, args.epochs ,args.batch_size, args.lr)