# Description

DokuVimNG is a Neovim plugin that allows you to edit [DokuWiki](https://dokuwiki.org) pages via it's xml-rpc interface. It also does syntax highlighting for DokuWiki syntax.

The whole code is initially taken from [dokuvimki](https://github.com/kynan/dokuwiki) and updated to Neovim's lua configuration plus using the new style pynvim plugin stuff.

It's extended with more features like pasting images from clipboard, handling namespace switching and integrating KeePassXC credentials lookup via browser api.

## Requirements

Requires Neovim
Requires python >= `3x`
Requires [python-keepassxc-browser](https://github.com/hrehfeld/python-keepassxc-browser) (only if keepassxc integration is used)
sRequires [python-dokuwiki](https://github.com/fmenabe/python-dokuwiki)

## Installation

Install the plugin with your preferred package manager:

### [lazy.nvim](https://github.com/folke/lazy.nvim)

```lua
  return {
    "mfulz/DokuVimNG",
      config = function()
        require("DokuVimNG").setup{
          urls = {
            "https://my.dokuwiki.url",
            "https://other.dokuwiki.url",
          },
          creds = {
            { user = "user1", pass = "pass1" },
            { user = "user2", pass = "pass2" },
          },
        }
      end,
  }
}
```

<details>
<summary>More complete setup</summary>

```lua
  return {
    "mfulz/DokuVimNG",
      config = function()
        require("DokuVimNG").setup{
          urls = {
            "https://my.dokuwiki.url",
          },
          keepassxc = true,
          keepassxc_match {
            field = "name",
            match = "dokuwiki",
            rule = "contains",
          },
        }
      end,
  }
```

</details>

## Configuration

DokuVimNG comes with the following defaults:

```lua
    {
      index_winwidth = 40,
      save_summary = "[DokuVimNG edit]",
      image_sub_ns = "images",
      keys = {
          init = "<Leader>Wi",
          edit = "<Leader>We",
          cd = "<Leader>Wc",
          search = "<Leader>Ws",
          mediasearch = "<Leader>Wm",
          paste_image = "<Leader>Wpi",
          paste_image_link = "<Leader>Wpl",
      },
      urls = {},
      creds = {},
      keepassxc = false,
      keepassxc_id = "DokuVimNG",
      keepassxc_match {
        field = "name",
        match = "",
        rule = "contains",
      },
      keepassxc_state_file = "~/.DokuVimNG.state",
    }
```

### Configuration

#### index_winwidth

Default : `40`

Define the width of the index window

#### save_summary

Default : `[DokuVimNG edit]`

The default summary used for dokuwiki changes

#### image_sub_ns

Default : `images`

The namespace used as sub namespace when pasting images

#### urls

Default : ``

List of urls that should be handled by DokuVimNG. This must be set in the
configuration

#### creds

Default : ``

List of maps `{ user = "login_name", pass = "user_pass" }` to be used for
dokuwiki logins.
This must be set if keepassxc is set to `false`

#### keepassxc

Default : `false`

If set to `true` DokuVimNG will use the KeePassXC browser api to look for
credentials. Will override CREDS

#### keepassxc_id

Default : `DokuVimNG`

The identifier used for KeePassXC browser api

#### keepassxc_match

A simple match rule definition for keepass credentials

##### keepassxc_match.field

Default : `"name"`

The field to compare against the requested value from the KeePassXC reponse
`"name"`, `"group"`, `"login"`, etc.

##### keepassxc_match.match

Default : `""`

The value that should be matched. If empty it will return all found
credentials.

##### keepassxc_match.rule

The rule to match with `"contains"` or `"equals"` where the first one looks
for the match to be in the value and the second one checks for equality.

#### keepassxc_state_file

Default : `~/.DokuVimNG.state`

The state file to save the KeePassXC browser api login credentials

