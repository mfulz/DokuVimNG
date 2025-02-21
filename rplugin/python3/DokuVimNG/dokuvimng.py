import sys
import os
import re

from pathlib import Path

from PIL import ImageGrab
from tempfile import TemporaryDirectory

import time
import pynvim

__author__ = "Matthias Fulz <mfulz@olznet.de>"
__license__ = "MIT"
__maintainer__ = "Matthias Fulz <mfulz@olznet.de>"

try:
    import dokuwiki

    has_dokuwiki = True
except ImportError:
    has_dokuwiki = False

try:
    from keepassxc_browser import Connection, Identity, ProtocolError

    has_keepassxc = True
except ImportError:
    has_keepassxc = False


@pynvim.plugin
class DokuVimNG:
    """
    Glue class to provide the functionality to interface between the DokuWiki API and vim.
    """

    def __init__(self, nvim):
        self._nvim = nvim
        self.initialized = False

    def init(self):
        if self.xmlrpc_init():
            self.buffers = {}
            self.buffers["search"] = Buffer(self._nvim, "search", "nofile")
            self.buffers["backlinks"] = Buffer(self._nvim, "backlinks", "nofile")
            self.buffers["revisions"] = Buffer(self._nvim, "revisions", "nofile")
            self.buffers["changes"] = Buffer(self._nvim, "changes", "nofile")
            self.buffers["index"] = Buffer(self._nvim, "index", "nofile")
            self.buffers["media"] = Buffer(self._nvim, "media", "nofile")
            self.buffers["help"] = Buffer(self._nvim, "help", "nofile")

            self.needs_refresh = False
            self.diffmode = False

            self.hdlevel = 0
            self.headlines = ["=====  =====", "====  ====", "===  ===", "== =="]

            self.cur_ns = ""
            self.pages = []

            self.default_sum = self.cfg["save_summary"]
            self.img_sub_ns = self.cfg["image_sub_ns"]

            self.index_winwith = self.cfg["index_winwidth"]
            self.index(self.cur_ns, True)

            splitright = self._nvim.options["splitright"]
            if splitright:
                self._nvim.command("set splitright!")

            self._nvim.command("set laststatus=2")
            self._nvim.command("silent! {} vsplit".format(self.index_winwith))

            if splitright:
                self._nvim.command("set splitright")

            self.initialized = True

            self.help()
            # vim.command(
            #     "command! -nargs=0 DokuVimKi echo 'DokuVimKi is already running!'"
            # )
            return True
        return False

    @pynvim.function("DWNsetUrl")
    def dwn_set_url(self, args):
        self.dw_url = args[0]
        self.get_login()

    @pynvim.function("DWNsetUser")
    def dwn_set_user(self, args):
        self.dw_user = args[0]["user"]
        self.dw_pass = args[0]["pass"]
        self.init()

    def get_url(self):
        self._nvim.exec_lua('require("DokuVimNG").selectUrl()')

    def get_login(self):
        if not self.cfg["keepassxc"]:
            self._nvim.exec_lua('require("DokuVimNG").selectCredential()')
        else:
            try:
                self.get_login_keepassxc()
            except Exception as err:
                self._nvim.err_write(
                    "Error getting credentials from KeePassXC: {}\n".format(err)
                )

    def get_login_keepassxc(self):
        if not has_keepassxc:
            raise Exception("Python moodule keepassxc_browser missing")

        client_id = self.cfg["keepassxc_id"]
        state_file = Path(os.path.expanduser(self.cfg["keepassxc_state_file"]))
        if state_file.exists():
            with state_file.open("r") as f:
                data = f.read()
            id = Identity.unserialize(client_id, data)
        else:
            id = Identity(client_id)

        c = Connection()
        c.connect()
        c.change_public_keys(id)

        db_hash = c.get_database_hash(id)
        if not c.test_associate(id):
            self._nvim.out_write("Not associated with keepassxc, trying now...\n")
            c.associate(id)
            data = id.serialize()
            with state_file.open("w") as f:
                f.write(data)
            del data

        choices = "{"
        logins = c.get_logins(id, url=self.dw_url)
        for login in logins:
            matcher = self.cfg["keepassxc_match"]
            if len(matcher) > 0:
                field = matcher["field"]
                match = matcher["match"]
                rule = matcher["rule"]

                if match:
                    value = login.get(field, "")
                    if value:
                        if rule == "contains":
                            if match not in value:
                                continue
                        elif rule == "equals":
                            if match != value:
                                continue
            choices = "{}{{user='{}',pass='{}',group='{}',name='{}'}},".format(
                choices,
                login.get("login", ""),
                login.get("password", ""),
                login.get("group", ""),
                login.get("name", ""),
            )
        choices = "{}}}".format(choices)
        self._nvim.exec_lua('require("DokuVimNG").selectCredential({})'.format(choices))

    def xmlrpc_init(self):
        """
        Establishes the xmlrpc connection to the remote wiki.
        """

        try:
            self.xmlrpc = dokuwiki.DokuWiki(
                self.dw_url, self.dw_user, self.dw_pass, cookieAuth=True
            )
            return True
        except (dokuwiki.DokuWikiError, Exception) as err:
            self._nvim.err_write("DokuVimNG Error: {}\n".format(err))
            return False

    @pynvim.command("DWNinit", nargs=0, sync=True)
    def dwn_init(self):
        if self.initialized:
            return True

        if not has_dokuwiki:
            self._nvim.err_write("DokuVimNG Error: Missing dokuwiki python module\n")
            return False

        self.cfg = self._nvim.exec_lua('return require("DokuVimNG").getConfig()')

        self.get_url()
        return False

    @pynvim.command("DWNhelp", nargs=0, sync=True)
    def help(self):
        """
        Shows the plugin help.
        """

        if self.diffmode:
            self.diff_close()

        self.focus(2)
        self._nvim.command("silent! buffer! {}".format(self.buffers["help"].num))
        self._nvim.command("silent! set buftype=help")

        self._nvim.command("help DokuVimNG")
        self._nvim.command("setlocal statusline=%{'[help]'}")

    @pynvim.function("DWNcompletePages", sync=True)
    def dwn_complete_pages(self, args):
        if not self.dwn_init():
            return

        if len(args) != 3:
            self._nvim.err_write("Wrong number of arguments\n")
            return

        ret = []
        matches = []
        arglead = args[0]
        cmdline = args[1]
        cursorpos = int(args[2])

        for page in self.pages:
            if page.startswith(arglead):
                ret.append(page)

        return ret

    @pynvim.command(
        "DWNedit", nargs=1, complete="customlist,DWNcompletePages", sync=True
    )
    def dwn_edit(self, args):
        if not self.dwn_init():
            return

        self.edit(args[0])

    def edit(self, wp, rev=""):
        """
        Opens a given wiki page, or a given revision of a wiki page for
        editing or switches to the correct buffer if the is open already.
        """

        self._nvim.out_write("editing pagename {}.\n".format(wp))
        wp = ":".join([x.strip().lower().replace(" ", "_") for x in wp.split(":")])

        if self.diffmode:
            self.diff_close()

        self.focus(2)

        if wp.find(":") == -1:
            wp = self.cur_ns + wp

        if (
            wp in self.buffers
            and self.buffers[wp].iswp
            and self.buffers[wp].type == "acwrite"
        ):
            self._nvim.command("silent! buffer! {}".format(self.buffers[wp].num))
            self.close(wp)

        if wp not in self.buffers:
            perm = int(self.xmlrpc.pages.permission(wp))

            if perm >= 1:
                try:
                    if rev:
                        text = self.xmlrpc.pages.get(wp, int(rev))
                    else:
                        text = self.xmlrpc.pages.get(wp)
                except dokuwiki.DokuWikiError as err:
                    self._nvim.err_write("\n".format(err))

                if text:
                    if perm == 1:
                        self._nvim.err_write(
                            "You don't have permission to edit {}. Opening readonly!\n".format(
                                wp
                            )
                        )
                        self.buffers[wp] = Buffer(self._nvim, wp, "nowrite", True)
                        self.buffers[wp].page[:] = text.split("\n")
                        self.buffers[wp].buf[:] = self.buffers[wp].page
                        self._nvim.command("setlocal nomodifiable")
                        self._nvim.command("setlocal readonly")

                    if perm >= 2:
                        if not self.lock(wp):
                            return

                        self._nvim.out_write("Opening {} for editing ...\n".format(wp))
                        self.buffers[wp] = Buffer(self._nvim, wp, "acwrite", True)
                        self.buffers[wp].page[:] = text.split("\n")
                        self.buffers[wp].buf[:] = self.buffers[wp].page

                        self._nvim.command("set nomodified")
                        self._nvim.command("autocmd! BufWriteCmd <buffer> DWNsave")
                        self._nvim.command("autocmd! FileWriteCmd <buffer> DWNsave")
                        self._nvim.command("autocmd! FileAppendCmd <buffer> DWNsave")

                if not text and perm >= 4:
                    self._nvim.out_write("Creating new page: {}\n".format(wp))
                    self.buffers[wp] = Buffer(self._nvim, wp, "acwrite", True)
                    self.needs_refresh = True

                    self._nvim.command("set nomodified")
                    self._nvim.command("autocmd! BufWriteCmd <buffer> DWNsave")
                    self._nvim.command("autocmd! FileWriteCmd <buffer> DWNsave")
                    self._nvim.command("autocmd! FileAppendCmd <buffer> DWNsave")

                self.switch_to_page_ns(wp)
                self._nvim.command(
                    'map <silent> <buffer> <enter> :call DWNbufferCmd("enter")<CR>'
                )
                self.buffer_setup()

            else:
                self._nvim.err_out(
                    "You don't have permissions to read/edit/create {}\n".format(wp)
                )
                return

        else:
            self.needs_refresh = False
            self._nvim.command("silent! buffer! {}".format(self.buffers[wp].num))

    def diff(self, revline):
        """
        Opens a page and a given revision in diff mode.
        """

        data = revline.split()
        wp = data[0]
        rev = data[2]
        date = time.strftime("%Y-%m-%d@%Hh%mm%Ss", time.localtime(float(rev)))

        if wp not in self.buffers:
            self.edit(wp)

        if rev not in self.buffers[wp].diff:
            text = self.xmlrpc.pages.get(wp, int(rev))
            if text:
                self.buffers[wp].diff[rev] = Buffer(
                    self._nvim, wp + "_" + date, "nofile"
                )
                self.buffers[wp].diff[rev].page[:] = text.split("\n")
            else:
                self._nvim.out_write("Error, couldn't load revision for diffing.\n")
                return

        self.focus(2)
        self._nvim.command("silent! buffer! {}".format(self.buffers[wp].num))
        self._nvim.command("vertical diffsplit")
        self.focus(3)
        self._nvim.command("silent! buffer! {}".format(self.buffers[wp].diff[rev].num))
        self._nvim.command("setlocal modifiable")
        self._nvim.command("abbr <buffer> close DWdiffclose")
        self._nvim.command("abbr <buffer> DWclose DWdiffclose")
        self.buffers[wp].diff[rev].buf[:] = self.buffers[wp].diff[rev].page
        self._nvim.command("setlocal nomodifiable")
        self.buffer_setup()
        self._nvim.command("diffthis")
        self.focus(2)
        self.diffmode = True

    @pynvim.command("DWNdiffClose", nargs=0, sync=True)
    def diff_close(self):
        """
        Closes the diff window.
        """

        self.focus(3)
        self._nvim.command("diffoff")
        self._nvim.command("close")
        self.diffmode = False
        self.focus(2)
        self._nvim.command("vertical resize")

    @pynvim.command("DWNsave", nargs="?", sync=True)
    def savecmd(self, args):
        if not self.dwn_init():
            return

        sum = ""
        if len(args) == 1:
            sum = args[0]

        self.save(sum)

    def save(self, sum="", minor=0):
        """
        Saves the current buffer. Works only if the buffer is a wiki page.
        Deleting wiki pages works like using the web interface, just delete all
        text and save.
        """

        wp = self._nvim.current.buffer.name.rsplit(os.sep, 1)[1]
        try:
            if not self.buffers[wp].iswp:
                self._nvim.err_write(
                    "Error: Current buffer {} is not a wiki page or not writeable!\n".format(
                        wp
                    )
                )
            elif self.buffers[wp].type == "nowrite":
                self._nvim.err_write(
                    "Error: Current buffer {} is readonly!\n".format(wp)
                )
            else:
                text = "\n".join(self.buffers[wp].buf)
                if text and not self.ismodified(wp):
                    self._nvim.out_write("No unsaved changes in current buffer.\n")
                elif not text and wp not in self.pages:
                    self._nvim.out_write("Can't save new empty page {}.\n".format(wp))
                else:
                    if not sum and text:
                        sum = self.default_sum
                        minor = 1

                    try:
                        self.xmlrpc.pages.set(wp, text, sum=sum, minor=minor)
                        self.buffers[wp].page[:] = self.buffers[wp].buf
                        self.buffers[wp].need_save = False

                        if text:
                            self._nvim.command(
                                "silent! buffer! {}".format(self.buffers[wp].num)
                            )
                            self._nvim.command("set nomodified")
                            self._nvim.out_write("Page {} written!\n".format(wp))

                            if self.needs_refresh:
                                self.index(self.cur_ns, True)
                                self.needs_refresh = False
                                self.focus(2)
                        else:
                            self._nvim.out_write("Page {} removed!\n".format(wp))
                            self.close(wp)
                            self.index(self.cur_ns, True)
                            self.focus(2)

                    except dokuwiki.DokuWikiError as err:
                        self._nvim.err_write("DokuVimKi Error: {}\n".format(err))
        except KeyError as err:
            self._nvim.err_write(
                "Error: Current buffer {} is not handled by DWsave!\n".format(wp)
            )

    def upload(self, file, overwrite=False):
        """
        Uploads a file to the remote wiki.
        """

        path = os.path.realpath(file)
        fname = os.path.basename(path)

        if os.path.isfile(path):
            try:
                fh = open(path, "rb")
                data = fh.read()
                file_id = self.cur_ns + fname
                try:
                    self.xmlrpc.medias.set(file_id, data, overwrite)
                    self._nvim.out_write("Uploaded {} successfully.\n".format(fname))
                    self.refresh()
                    return True
                except dokuwiki.DokuWikiError as err:
                    self._nvim.err_write("{}\n".format(err))
                    return False
            except (IOError, Exception) as err:
                self._nvim.err_write("{}\n".format(err))
                return False
        else:
            self._nvim.err_write("{} is not a file\n".format(path))
            return False

    @pynvim.command("DWNpasteImage", nargs="*", sync=True)
    def dwn_paste_image(self, args):
        if len(args) > 3:
            self._nvim.err_write("Wrong number of arguments\n")
            return

        link = False
        after = False
        silent = False
        if len(args) >= 1:
            if args[0] == "True":
                link = True
        if len(args) >= 2:
            if args[1] == "True":
                after = True
        if len(args) >= 3:
            if args[2] == "True":
                silent = True

        self.paste_image(link=link, after=after, silent=silent)

    def paste_image(self, link=False, after=False, silent=False):
        img = ImageGrab.grabclipboard()
        if img is None:
            return

        with TemporaryDirectory() as tmpdir:
            img_name = ""
            if not silent:
                img_name = self._nvim.exec_lua("return vim.fn.input('File Name? ', '')")
                img_name = os.path.basename(img_name)
            if img_name == "":
                timestamp = int(time.time())
                img_name = f"image_{timestamp}"

            img_path = os.path.abspath(os.path.join(tmpdir, f"{img_name}.png"))
            img.save(img_path, "PNG")

            img_ns = self.cur_ns
            if self.img_sub_ns:
                img_ns = f"{img_ns}{self.img_sub_ns}:"

            old_ns = self.cur_ns
            self.cur_ns = img_ns
            if not self.upload(img_path, True):
                self.cur_ns = old_ns
                return
            self.cur_ns = old_ns

            img_url = f"{img_ns}{img_name}.png"
            pattern = img_url
            if link:
                pattern = "{{" + img_url + "}}"

            if self._nvim.eval("mode()") in ["v", "V"]:
                self._nvim.command(f"normal! c{pattern}")
            else:
                if after:
                    self._nvim.command(f"normal! a{pattern}")
                else:
                    self._nvim.command(f"normal! i{pattern}")

    # TODO: compl func for namespaces only
    @pynvim.command("DWNcd", nargs="?", complete="customlist,DWNcompletePages")
    def dwn_cd(self, args):
        if len(args) == 1:
            self.cd(args[0])
        else:
            self.cd()

    def cd(self, query=""):
        """
        Changes into the given namespace.
        """

        if query and query[-1] != ":":
            query += ":"

        self.index(query)

    @pynvim.function("DWNindex", sync=True)
    def dwn_index(self, args):
        if not self.dwn_init():
            return

        self.index("", args[0])

    def index(self, query="", refresh=False):
        """
        Build the index used to navigate the remote wiki.
        """

        index = []
        pages = []
        dirs = []

        self.focus(1)
        self._nvim.command("set winwidth={}".format(self.index_winwith))
        self._nvim.command("set winminwidth={}".format(self.index_winwith))

        self._nvim.command("silent! buffer! {}".format(self.buffers["index"].num))
        self._nvim.command("setlocal modifiable")
        self._nvim.command("setlocal nonumber")
        self._nvim.command(r"syn match DokuVimKi_NS /^.*\//")
        self._nvim.command("syn match DokuVimKi_CURNS /^ns:/")

        self._nvim.command(
            "hi DokuVimKi_NS term=bold cterm=bold ctermfg=LightBlue gui=bold guifg=LightBlue"
        )
        self._nvim.command(
            "hi DokuVimKi_CURNS term=bold cterm=bold ctermfg=Yellow gui=bold guifg=Yellow"
        )

        if refresh:
            self.refresh()

        if query and query[-1] != ":":
            self.edit(query)
            return
        else:
            self.cur_ns = query

        if self.pages:
            for page in self.pages:
                if not query:
                    if ":" not in page:
                        pages.append(page)
                    else:
                        ns = page.split(":", 1)[0] + "/"
                        if ns not in dirs:
                            dirs.append(ns)
                else:
                    if re.search("^" + query, page):
                        page = page.replace(query, "")
                        if page.find(":") == -1:
                            if page not in index:
                                pages.append(page)
                        else:
                            ns = page.split(":", 1)[0] + "/"
                            if ns not in dirs:
                                dirs.append(ns)

            index.append("ns: " + self.cur_ns)

            if query:
                index.append(".. (up a namespace)")

            index.append("")

            pages.sort()
            dirs.sort()
            index = index + dirs + pages

            self.buffers["index"].buf[:] = index

            self._nvim.command(
                'map <silent> <buffer> <enter> :call DWNcmd("index")<CR>'
            )
            self._nvim.command('map <silent> <buffer> r :call DWNcmd("revisions")<CR>')
            self._nvim.command('map <silent> <buffer> b :call DWNcmd("backlinks")<CR>')
            self._nvim.command('map <silent> <buffer> R :call DWNindex("True")<CR>')

            self._nvim.command("setlocal nomodifiable")
            self._nvim.command("2")

    @pynvim.command("DWNchanges", nargs="?")
    def dwn_changes(self, args):
        if len(args) == 1:
            self.changes(args[0])
        else:
            self.changes()

    def changes(self, timeframe=False):
        """
        Shows the last changes on the remote wiki.
        """

        if self.diffmode:
            self.diff_close()

        self.focus(2)

        self._nvim.command("silent! buffer! {}".format(self.buffers["changes"].num))
        self._nvim.command("setlocal modifiable")

        if not timeframe:
            timestamp = int(time.time()) - (60 * 60 * 24 * 7)
        else:
            m = re.match(r"(?P<num>\d+)(?P<type>[dw]{1})", timeframe)
            if m:
                argv = m.groupdict()

                if argv["type"] == "d":
                    timestamp = int(time.time()) - (60 * 60 * 24 * int(argv["num"]))
                elif argv["type"] == "w":
                    timestamp = int(time.time()) - (
                        60 * 60 * 24 * (int(argv["num"]) * 7)
                    )
                else:
                    self._nvim.err_write(
                        "Wrong timeframe format {}.\n".format(timeframe)
                    )
                    return
            else:
                self._nvim.err_write("Wrong timeframe format {}.\n".format(timeframe))
                return

        try:
            changes = self.xmlrpc.pages.changes(timestamp)
            if len(changes) > 0:
                maxlen = max(len(change["name"]) for change in changes)
                fmt = "{name:" + str(maxlen) + "}\t{lastModified}\t{version}\t{author}"
                self.buffers["changes"].buf[:] = list(
                    reversed([fmt.format(**change) for change in changes])
                )
                self._nvim.command(r"syn match DokuVimKi_REV_PAGE /^\(\w\|:\)*/")
                self._nvim.command(r"syn match DokuVimKi_REV_TS /\s\d*\s/")

                self._nvim.command(
                    "hi DokuVimKi_REV_PAGE cterm=bold ctermfg=Yellow gui=bold guifg=Yellow"
                )
                self._nvim.command(
                    "hi DokuVimKi_REV_TS cterm=bold ctermfg=Yellow gui=bold guifg=Yellow"
                )

                self._nvim.command("setlocal nomodifiable")
                self._nvim.command(
                    "map <silent> <buffer> <enter> :call DWNrevEdit()<CR>"
                )

            else:
                print("DokuVimKi Error: No changes", file=sys.stderr)

        except dokuwiki.DokuWikiError as err:
            self._nvim.err_write("\n".format(err))

    @pynvim.command(
        "DWNrevisions", nargs="*", complete="customlist,DWNcompletePages", sync=True
    )
    def dwn_revisions(self, args):
        if not self.dwn_init():
            return

        argslen = len(args)
        wp = ""
        first = 0
        if argslen == 1:
            wp = args[0]
        elif argslen == 2:
            wp = args[0]
            first = args[1]
        elif argslen > 2:
            self._nvim.err_write("Wrong number of arguments\n")
            return

        self.revisions(wp, first)

    def revisions(self, wp="", first=0):
        """
        Display revisions for a certain page if any.
        """

        if self.diffmode:
            self.diff_close()

        if not wp or wp[-1] == ":":
            return

        try:
            self.focus(2)

            self._nvim.command(
                "silent! buffer! {}".format(self.buffers["revisions"].num)
            )
            self._nvim.command("setlocal modifiable")

            revs = self.xmlrpc.pages.versions(wp, int(first))
            if revs:
                self.buffers["revisions"].buf[:] = [
                    wp
                    + "\t"
                    + "\t".join(
                        str(rev[x])
                        for x in ["modified", "version", "ip", "type", "user", "sum"]
                    )
                    for rev in revs
                ]
                self._nvim.out_write("loaded revisions for :{}\n".format(wp))
                self._nvim.command(
                    "map <silent> <buffer> <enter> :call DWNrevEdit()<CR>"
                )

                self._nvim.command(r"syn match DokuVimKi_REV_PAGE /^\(\w\|:\)*/")
                self._nvim.command(r"syn match DokuVimKi_REV_TS /\s\d*\s/")
                self._nvim.command(r"syn match DokuVimKi_REV_CHANGE /\s\w\{1}\s/")

                self._nvim.command(
                    "hi DokuVimKi_REV_PAGE term=bold cterm=bold ctermfg=Yellow gui=bold guifg=Yellow"
                )
                self._nvim.command(
                    "hi DokuVimKi_REV_TS term=bold cterm=bold ctermfg=Yellow gui=bold guifg=Yellow"
                )
                self._nvim.command(
                    "hi DokuVimKi_REV_CHANGE term=bold cterm=bold ctermfg=Yellow gui=bold guifg=Yellow"
                )

                self._nvim.command("setlocal nomodifiable")
                self._nvim.command('map <silent> <buffer> d :call DWNcmd("diff")<CR>')

            else:
                self._nvim.err_write(
                    "DokuVimKi Error: No revisions found for page: {}\n".format(wp)
                )
        except dokuwiki.DokuWikiError as err:
            self._nvim.err_write("DokuVimKi XML-RPC Error: {}\n".format(err))

    @pynvim.function("DWNrefreshIndex", sync=True)
    def dwn_refresh_index(self, args):
        if len(args) > 1:
            self._nvim.err_write("Wrong number of arguments\n")
            return

        wp = ""
        self._nvim.command("autocmd! BufEnter <buffer>")
        if len(args) == 1:
            wp = args[0]
        self.index(wp)
        self.focus(2)
        self._nvim.command(
            'autocmd! BufEnter <buffer> :call DWNrefreshIndex("{}")'.format(wp)
        )

    @pynvim.command(
        "DWNbacklinks", nargs="?", complete="customlist,DWNcompletePages", sync=True
    )
    def dwn_backlinks(self, args):
        if not self.dwn_init():
            return

        wp = ""
        if len(args) == 1:
            wp = args[0]

        self.backlinks(wp)

    def backlinks(self, wp=""):
        """
        Display backlinks for a certain page if any.
        """

        if self.diffmode:
            self.diff_close()

        if not wp or wp[-1] == ":":
            return

        try:
            self.focus(2)

            self._nvim.command(
                "silent! buffer! {}".format(self.buffers["backlinks"].num)
            )
            self._nvim.command("setlocal modifiable")

            blinks = self.xmlrpc.pages.backlinks(wp)

            if len(blinks) > 0:
                self.buffers["backlinks"].buf[:] = list(map(str, blinks))
                self._nvim.command('map <buffer> <enter> :call DWNcmd("edit")<CR>')
                self.dwn_refresh_index("")
            else:
                self._nvim.err_write(
                    "DokuVimKi Error: No backlinks found for page: {}\n".format(wp)
                )
            self._nvim.command("setlocal nomodifiable")

        except dokuwiki.DokuWikiError as err:
            self._nvim.err_write("DokuVimKi XML-RPC Error: {}\n".format(err))

    @pynvim.command("DWNsearch", nargs="?")
    def dwn_search(self, args):
        if len(args) == 1:
            self.search("page", args[0])
        else:
            self.search("page")

    @pynvim.command("DWNmediasearch", nargs="?")
    def dwn_media_search(self, args):
        if len(args) == 1:
            self.search("media", args[0])
        else:
            self.search("media")

    def search(self, type="", pattern=""):
        """
        Search the page list for matching pages and display them for editing.
        """

        if self.diffmode:
            self.diff_close()

        self.focus(2)

        try:
            if type == "page":
                self._nvim.command(
                    "silent! buffer! {}".format(self.buffers["search"].num)
                )
                self._nvim.command("setlocal modifiable")

                if pattern:
                    p = re.compile(pattern)
                    result = list(filter(p.search, self.pages))
                else:
                    result = self.pages

                if len(result) > 0:
                    self.buffers["search"].buf[:] = result
                    self._nvim.command('map <buffer> <enter> :call DWNcmd("edit")<CR>')
                else:
                    self._nvim.err_write("DokuVimKi Error: No matching pages found!\n")

            elif type == "media":
                self._nvim.command(
                    "silent! buffer! {}".format(self.buffers["media"].num)
                )
                self._nvim.command("setlocal modifiable")

                if pattern:
                    p = re.compile(pattern)
                    result = list(filter(p.search, self.media))
                else:
                    result = self.media

                if len(result) > 0:
                    self.buffers["media"].buf[:] = result
                else:
                    self._nvim.err_write(
                        "DokuVimKi Error: No matching media files found!\n"
                    )

            self._nvim.command("setlocal nomodifiable")

        except:
            pass

    @pynvim.command("DWNclose", bang=True, nargs=0, sync=True)
    def close(self, buffer, bang=False):
        if not self.dwn_init():
            return

        """
        Closes the given buffer. Works only if the given buffer is a wiki
        page.  The buffer is also removed from the buffer stack.
        """

        if self.diffmode:
            self.diff_close()
            return

        try:
            if self.buffers[buffer].iswp:
                if not bang and self.ismodified(buffer):
                    self._nvim.err_write(
                        "Warning: {} contains unsaved changes! Use DWclose!.\n".format(
                            buffer
                        )
                    )
                    return

                self._nvim.command("bp!")
                # Ignore any failure deleting this buffer e.g. if it has been manually deleted before
                self._nvim.command("silent! bdel! {}".format(self.buffers[buffer].num))
                if self.buffers[buffer].type == "acwrite":
                    self.unlock(buffer)
                del self.buffers[buffer]
            else:
                self._nvim.err_write(
                    'You cannot close special buffer "{}"!\n'.format(buffer)
                )

        except KeyError:
            self._nvim.err_write(
                'You cannot use DWclose on non wiki page "{}"!\n'.format(buffer)
            )

    @pynvim.command("DWNquit", bang=True, nargs=0, sync=True)
    def quit(self, bang):
        if not self.dwn_init():
            return

        """
        Quits the current session.
        """

        unsaved = []

        for buffer in list(self.buffers):
            if self.buffers[buffer].iswp:
                if not self.ismodified(buffer):
                    self._nvim.command(
                        "silent! buffer! {}".format(self.buffers[buffer].num)
                    )
                    self.close(buffer)
                elif self.ismodified(buffer) and bang:
                    self._nvim.command(
                        "silent! buffer! {}".format(self.buffers[buffer].num)
                    )
                    self.close(buffer, bang=True)
                else:
                    unsaved.append(buffer)

        if len(unsaved) == 0:
            self._nvim.command("silent! quitall")
        else:
            print(
                "Some buffers contain unsaved changes. Use DWquit! if you really want to quit.",
                file=sys.stderr,
            )

    def ismodified(self, buffer):
        """
        Checks whether the current buffer or a given buffer is modified or not.
        """

        if self.buffers[buffer].need_save:
            return True
        elif (
            "\n".join(self.buffers[buffer].page).strip()
            != "\n".join(self.buffers[buffer].buf).strip()
        ):
            return True
        else:
            return False

    @pynvim.function("DWNrevEdit", sync=True)
    def rev_edit(self, args=None):
        if not self.dwn_init():
            return

        """
        Special mapping for editing revisions from the revisions listing.
        """

        row, col = self._nvim.current.window.cursor
        wp = self._nvim.current.buffer[row - 1].split("\t")[0].strip()
        rev = self._nvim.current.buffer[row - 1].split("\t")[2].strip()
        self.edit(wp, rev)

    def focus(self, winnr):
        """
        Convenience function to switch the current window focus.
        """

        if int(self._nvim.eval("winnr()")) != winnr:
            self._nvim.command(str(winnr) + "wincmd w")

    def refresh(self):
        """
        Refreshes the page index by retrieving a fresh list of all pages on the
        remote server and updating the completion dictionary.
        """

        self.pages = []
        self.media = []

        try:
            print("Refreshing page index!", file=sys.stdout)
            data = self.xmlrpc.pages.list()

            if data:
                for page in data:
                    page = page["id"]
                    self.pages.append(page)
                    # Add the page's namespace if not the root namespace
                    if ":" not in page:
                        continue
                    ns = page.rsplit(":", 1)[0] + ":"
                    if ns not in self.pages:
                        self.pages.append(ns)
                        self.media.append(ns)

            self.pages.sort()

            self._nvim.out_write("Refreshing media index!\n")
            data = self.xmlrpc.medias.list()

            if data:
                for media in data:
                    self.media.append(media["id"])

            self.media.sort()

        except dokuwiki.DokuWikiError as err:
            self._nvim.err_write(
                "Failed to fetch page list. Please check your configuration {}\n".format(
                    err
                )
            )

    def lock(self, wp):
        """
        Tries to obtain a lock given wiki page.
        """

        try:
            self.xmlrpc.pages.lock(wp)
            return True
        except dokuwiki.DokuWikiError as err:
            self._nvim.err_write("{}\n".format(err))
            return False

    def unlock(self, wp):
        """
        Tries to unlock a given wiki page.
        """

        try:
            self.xmlrpc.pages.unlock(wp)
            return True
        except dokuwiki.DokuWikiError as err:
            # self._nvim.err_write("{}\n".format(err))
            return False

    @pynvim.function("DWNbufferCmd", sync=True)
    def buffer_cmd(self, args):
        if not self.dwn_init():
            return

        if len(args) != 1:
            self._nvim.err_write("Wrong number of arguments\n")
            return

        if args[0] == "enter":
            row, col = self._nvim.current.window.cursor
            line = self._nvim.current.buffer[row - 1]
            if re.search("\[\[.*\|", line):
                self.edit(re.findall("\[\[.*\|", line)[0][2:-1])

    @pynvim.function("DWNcmd", sync=True)
    def dwn_cmd(self, args):
        if not self.dwn_init():
            return

        if len(args) != 1:
            self._nvim.err_write("Wrong number of arguments\n")
            return

        self.cmd(args[0])

    def cmd(self, cmd):
        """
        Callback function to provides various functionality for the page index
        (like open namespaces or triggering edit showing backlinks etc).
        """

        row, col = self._nvim.current.window.cursor
        line = self._nvim.current.buffer[row - 1]

        # first line triggers nothing in index buffer
        if row == 1 and line.find("ns: ") != -1:
            return

        if line.find("..") == -1:
            if line.find("/") == -1:
                if not line:
                    self._nvim.out_write("meh\n")
                else:
                    line = self.cur_ns + line
            else:
                line = self.cur_ns + line.replace("/", ":")
        else:
            line = self.cur_ns.rsplit(":", 2)[0] + ":"
            if line == ":" or line == self.cur_ns:
                line = ""

        callback = getattr(self, cmd)
        callback(line)

    def switch_to_page_ns(self, wp):
        if not self.buffers[wp].iswp:
            return

        parts = wp.split(":")
        new_ns = ""
        for i in range(len(parts) - 1):
            new_ns = "{}{}:".format(new_ns, parts[i])
        if new_ns != self.cur_ns:
            self.index(new_ns)
            self.focus(2)

    @pynvim.function("DWNbufferEnter", sync=True)
    def dwn_buffer_enter(self, args):
        if not self.dwn_init():
            return

        if len(args) != 1:
            self._nvim.err_write("Wrong number of arguments\n")
            return
        self.buffer_enter(args[0])

    def buffer_enter(self, wp):
        """
        Loads the buffer on enter.
        """

        self.buffers[wp].buf[:] = self.buffers[wp].page
        self._nvim.command("setlocal nomodified")
        self.buffer_setup()
        if self.buffers[wp].type == "acwrite":
            self.switch_to_page_ns(wp)

    @pynvim.function("DWNbufferLeave", sync=True)
    def dwn_buffer_leave(self, args):
        if not self.dwn_init():
            return

        self.buffer_leave(args[0])

    def buffer_leave(self, wp):
        if (
            "\n".join(self.buffers[wp].buf).strip()
            != "\n".join(self.buffers[wp].page).strip()
        ):
            self.buffers[wp].page[:] = self.buffers[wp].buf
            self.buffers[wp].need_save = True

    @pynvim.function("DWNheadline", sync=True)
    def dwn_headline(self, args):
        hl = self.headlines[self.hdlevel]
        if len(args) == 1:
            idx = int(args[0])
            if idx >= 0 and idx < len(self.headlines):
                hl = self.headlines[idx]
        return hl

    @pynvim.function("DWNsetLvl", sync=True)
    def dwn_setlevel(self, args):
        diff = 1
        if len(args) >= 1:
            diff = int(args[0])
            nlvl = self.hdlevel + diff
        if len(args) == 2:
            diff = int(args[0])
            nlvl = self.hdlevel - diff
        if nlvl < 0:
            self.hdlevel = 0
        elif nlvl >= len(self.headlines):
            self.hdlevel = len(self.headlines) - 1
        else:
            self.hdlevel = nlvl

    def buffer_setup(self):
        self._nvim.command("setlocal textwidth=0")
        self._nvim.command("setlocal wrap")
        self._nvim.command("setlocal linebreak")
        self._nvim.command("setlocal syntax=dokuwiki")
        self._nvim.command("setlocal filetype=dokuwiki")
        self._nvim.command("setlocal tabstop=2")
        self._nvim.command("setlocal expandtab")
        self._nvim.command("setlocal shiftwidth=2")
        self._nvim.command("setlocal encoding=utf-8")
        self._nvim.command("imap <buffer> <silent> <C-D><C-B> ****<ESC>1hi")
        self._nvim.command("imap <buffer> <silent> <C-D><C-I> ////<ESC>1hi")
        self._nvim.command("imap <buffer> <silent> <C-D><C-U> ____<ESC>1hi")
        self._nvim.command("imap <buffer> <silent> <C-D><C-L> [[]]<ESC>1hi")
        self._nvim.command("imap <buffer> <silent> <C-D><C-M> {{}}<ESC>1hi")
        self._nvim.command(
            "imap <buffer> <silent> <C-D><C-K> <code><CR><CR></code><ESC>ki"
        )
        self._nvim.command(
            "imap <buffer> <silent> <C-D><C-F> <file><CR><CR></file><ESC>ki"
        )
        self._nvim.command("imap <buffer> <silent> <expr> <C-D><C-H> DWNheadline()")
        self._nvim.command("map <buffer> <silent> <C-D><C-P> :call DWNsetLvl(1)<CR>")
        self._nvim.command("map <buffer> <silent> <C-D><C-D> :call DWNsetLvl(1, 1)<CR>")


class Buffer:
    """
    Representates a vim buffer object. Used to manage keep track of all opened
    pages and to handle the dokuvimki special buffers.

        self.num    = buffer number (starts at 1)
        self.id     = buffer id (starts at 0)
        self.buf    = vim buffer object
        self.name   = buffer name
        self.iswp   = True if buffer represents a wiki page
    """

    id = None
    num = None
    name = None
    buf = None

    def __init__(self, nvim, name, type, iswp=False):
        """
        Instanziates a new buffer.
        """
        self._nvim = nvim
        self._nvim.command("badd " + name)
        self.num = self._nvim.eval('bufnr("' + name + '")')

        # buffers are numbered from 0 in vim 7.3 and older
        # and from 1 in vim 7.4 and newer
        self.id = int(self.num)
        self.buf = self._nvim.buffers[self.id]
        self.name = name
        self.iswp = iswp
        self.type = type
        self.page = []
        self.need_save = False
        self._nvim.command("silent! buffer! {}".format(self.num))
        self._nvim.command("setlocal buftype=" + type)
        self._nvim.command("abbr <silent> close DWNclose")
        self._nvim.command("abbr <silent> close! DWNclose!")
        self._nvim.command("abbr <silent> quit DWNquit")
        self._nvim.command("abbr <silent> quit! DWNquit!")
        self._nvim.command("abbr <silent> q DWNquit")
        self._nvim.command("abbr <silent> q! DWNquit!")
        self._nvim.command("abbr <silent> qa DWNquit")
        self._nvim.command("abbr <silent> qa! DWNquit!")

        if type == "nofile":
            self._nvim.command("setlocal nobuflisted")
            self._nvim.command("setlocal nomodifiable")
            self._nvim.command("setlocal noswapfile")
            self._nvim.command("setlocal statusline=%{'[" + self.name + "]'}")

        if type == "acwrite":
            self.diff = {}
            self.need_save = False
            self._nvim.command(
                'autocmd! BufEnter <buffer> :call DWNbufferEnter("{}")'.format(
                    self.name
                )
            )
            self._nvim.command(
                'autocmd! BufLeave <buffer> :call DWNbufferLeave("{}")'.format(
                    self.name
                )
            )
            self._nvim.command(
                'autocmd! BufDelete <buffer> :DWNclose "{}"'.format(name)
            )
            self._nvim.command(
                r"setlocal statusline=%{'[wp]\ " + self.name + r"'}\ %r\ [%c,%l][%p]"
            )

        if type == "nowrite":
            self.diff = {}
            self._nvim.command(
                r"setlocal statusline=%{'[wp]\ " + self.name + r"'}\ %r\ [%c,%l][%p%%]"
            )
