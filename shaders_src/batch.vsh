//
//  batch.vsh
//
//

//%precompile

attribute vec4 a_Position;	//%attributeID MT_POS
attribute float a_Index;	//%attributeID MT_INDEX
uniform highp mat4 u_ModelToProjBatch[10];

void main()
{
	gl_Position = u_ModelToProjBatch[int(a_Index)] * a_Position;
}
