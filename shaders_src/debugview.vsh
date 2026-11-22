//%debugshader

//%debugfeature DEBUGVIEW_ALBEDO
//%debugfeature DEBUGVIEW_LIGHTMAP
//%debugfeature LIGHTMAP_TINT

//%include utility.xsh

attribute highp vec3 a_Position;	//%attributeID MT_POS
attribute highp vec2 a_TexCoord0;	//%attributeID MT_UV_0
attribute highp vec2 a_TexCoord1;	//%attributeID MT_UV_1

uniform highp mat4 u_ModelToProj;
varying highp vec2 v_TexCoord0;
varying highp vec2 v_TexCoord1;

const highp float c_zero = 0.0;
const mediump float texScale = 0.00048828125;
const mediump vec2 uvMult = vec2( texScale, -texScale );

void main()
{
	v_TexCoord0 = a_TexCoord0 * uvMult;
	v_TexCoord1 = a_TexCoord1 * uvMult;

	gl_Position = u_ModelToProj * vec4( a_Position, 1.0 );
}
