from pyvista import examples
import pyvista as pv
bolt_nut = examples.download_bolt_nut()
pl = pv.Plotter()
_ = pl.add_volume(bolt_nut, cmap="coolwarm")
pl.show()