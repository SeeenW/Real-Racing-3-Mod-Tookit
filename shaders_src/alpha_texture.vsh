//
//  alpha_texture.vsh
//
//  Created by jribaux.
//  Copyright EA 2012. All rights reserved.
//

//%feature BATCH_RENDER
//%precompile

// Inputs
// -----------------------------------
attribute vec4 a_Position;	//%attributeID MT_POS
attribute vec2 a_TexCoord0;	//%attributeID MT_UV_0

#ifdef BATCH_RENDER
	attribute float a_Index;		//%attributeID MT_INDEX
	attribute lowp vec4 a_Colour;	//%attributeID MT_COLOUR		Vertex colour

	uniform highp mat4 u_ModelToProjBatch[10];	// MUST MATCH #define DRAW_CALL_BATCH_SIZE in ManagerFontFT.h!!!
	varying lowp vec4 v_VertexColour;
#else
	uniform highp mat4 u_ModelToProj;
#endif

uniform highp mat3 u_TexMatrix0;

// Outputs
// -----------------------------------
varying highp vec2 v_TexCoord0;

void main()
{
	v_TexCoord0 = (u_TexMatrix0 * vec3( a_TexCoord0, 0 )).xy;
#ifdef BATCH_RENDER
	v_VertexColour = a_Colour;
	gl_Position = u_ModelToProjBatch[int(a_Index)] * a_Position;
#else
	gl_Position = u_ModelToProj * a_Position;
#endif
}
