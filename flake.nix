{
  description = "claude-config devShell — pinned python3 + ruff + shellcheck + shfmt, so Python-hook + shell contributors and CI resolve the SAME toolchain instead of drifting on the host's bash/python (macOS bash 3.2 vs 5, zsh vs bash — see CLAUDE.md's shell-drift lessons).";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    suxos-nix.url = "github:SuxOS/nix";
  };

  outputs = { self, nixpkgs, flake-utils, suxos-nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        # Composes on top of the shared Level-1 base (box-pinned ucode + jq + shellcheck)
        # instead of re-declaring it — this repo just adds what its own content needs:
        # python3 for the hooks + CI scripts, ruff for the pyflakes-only lint CI already runs,
        # shfmt to complement shellcheck's tracked-*.sh gate.
        devShells.default = pkgs.mkShell {
          inputsFrom = [ suxos-nix.devShells.${system}.default ];
          packages = [ pkgs.python3 pkgs.ruff pkgs.shellcheck pkgs.shfmt ];
          shellHook = "echo 'claude-config devShell'";
        };
      });
}
