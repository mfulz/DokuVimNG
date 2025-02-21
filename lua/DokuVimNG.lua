local keymap = {
	init = { cmd = ":DWNinit<CR>", silent = true },
	edit = { cmd = ":DWNedit<space>", silent = false },
	cd = { cmd = ":DWNcd<space>", silent = false },
	search = { cmd = ":DWNsearch<space>", silent = false },
	mediasearch = { cmd = ":DWNmediasearch<space>", silent = false },
	paste_image = { cmd = ":DWNpasteImage False True True<CR>", silent = true },
	paste_image_link = { cmd = ":DWNpasteImage True True True<CR>", silent = true },
}

local config = {
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
	keepassxc_match = {
		field = "name",
		match = "",
		rule = "equals",
	},
	keepassxc_state_file = "~/.DokuVimNG.state",
}

local function setup(cfg)
	for k, v in pairs(cfg) do
		config[k] = v
	end
	for k, v in pairs(config["keys"]) do
		vim.keymap.set("n", v, keymap[k]["cmd"], { silent = keymap[k]["silent"] })
	end
end

local function getConfig()
	return config
end

local function tablelength(T)
	local count = 0
	for _ in pairs(T) do
		count = count + 1
	end
	return count
end

local function selectUrl()
	if tablelength(config["urls"]) == 1 then
		local item = config["urls"][0] or config["urls"][1]
		vim.call("DWNsetUrl", item)
	else
		vim.ui.select(config.urls, { prompt = "select dokuwiki: " }, function(item)
			vim.call("DWNsetUrl", item)
		end)
	end
end

local function showChoice(item)
	local ret = "User: " .. item.user
	if item["group"] ~= nil then
		ret = ret .. "\t\tGroup: " .. item.group
	end
	if item["name"] ~= nil then
		ret = ret .. "\t\tName: " .. item.name
	end
	return ret
end

local function selectCredential(creds)
	local choices = {}
	if creds == nil then
		choices = config["creds"]
	else
		choices = creds
	end
	if tablelength(choices) == 1 then
		local item = choices[0] or choices[1]
		vim.call("DWNsetUser", item)
	else
		vim.ui.select(choices, { prompt = "select login credential: ", format_item = showChoice }, function(choice)
			vim.call("DWNsetUser", choice)
		end)
	end
end

return { setup = setup, getConfig = getConfig, selectUrl = selectUrl, selectCredential = selectCredential }
