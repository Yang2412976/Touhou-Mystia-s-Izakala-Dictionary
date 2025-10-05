
import pandas as pd
import os
import sys


def _find_resource(name: str) -> str | None:
	"""Return the first existing path for resource name by checking likely locations.

	Order: PyInstaller _MEIPASS, exe directory, script directory, current working directory.
	"""
	candidates = []
	# PyInstaller extracted folder
	if getattr(sys, 'frozen', False):
		meipass = getattr(sys, '_MEIPASS', None)
		if meipass:
			candidates.append(meipass)
		candidates.append(os.path.dirname(sys.executable))
	# script dir (development)
	try:
		script_dir = os.path.dirname(__file__)
	except Exception:
		script_dir = None
	if script_dir:
		candidates.append(script_dir)
	# current working directory
	candidates.append(os.getcwd())

	for d in candidates:
		if not d:
			continue
		p = os.path.join(d, name)
		if os.path.exists(p):
			return p
	return None


def load_dishes():
	"""从 dishes.txt 加载 dishes 变量并返回 DataFrame。

	This is robust to running from a PyInstaller one-file exe where data may be
	placed next to the executable. If no file is found, return an empty DataFrame.
	"""
	path = _find_resource('dishes.txt')
	if not path:
		# fallback: try package relative path
		try:
			base_dir = os.path.dirname(__file__)
			path = os.path.join(base_dir, 'dishes.txt')
			if not os.path.exists(path):
				return pd.DataFrame()
		except Exception:
			return pd.DataFrame()

	with open(path, 'r', encoding='utf-8') as f:
		content = f.read()
	ns = {}
	exec(content, ns)
	dishes = ns.get('dishes', [])
	return pd.DataFrame(dishes)


def search_by_tag(tag, checkpoint=None):
	if checkpoint is None:
		checkpoint = load_dishes()
	def has_tag(tags):
		try:
			return tag in tags
		except Exception:
			return False
	return checkpoint[checkpoint['tags'].apply(has_tag)]


if __name__ == '__main__':
	checkpoint = load_dishes()
	tag = input("请输入标签: ")
	results = search_by_tag(tag, checkpoint)
	print(results)